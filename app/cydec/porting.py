"""Persistent PS5 input preparation and verified, cancellable desktop porting jobs.

Container parsing, snapshots, receipts and tests belong to CyDecompilator. Optional
AnyPS5/UltraPack executables are separate tools; their code is not imported here.
"""
import hashlib
import json
import math
import os
import platform
import re
import shutil
import stat
import struct
import sys
import time
import uuid
import zipfile
from collections import Counter
from pathlib import Path, PurePosixPath

from cytools_core import CyToolError

from . import components, process
from .paths import SETTINGS, ENGINES, DOWNLOADS, read_json, write_json
from .project import sha256_file

TOOLS_FILE = SETTINGS / 'porting.json'
DEFAULT_LIMIT = 256 * 1024**3
FILE_LIMIT = 100000
SELF_MAGIC = b'O\x15=\x1d'
SELF_MAGICS = (SELF_MAGIC, b'T\x14\xf5\xee')
IMAGE_SUFFIXES = {'.pkg', '.ffpfs', '.ffpfsc', '.exfat', '.ffpkg', '.rar', '.7z'}
TOOL_FIELDS = ('relinker', 'windowsLibraries', 'linuxLibraries', 'ultrapackCli', 'ultrapackPython', 'ultrapackPkgTool')


def fail(message, code='InvalidParameters'):
    raise CyToolError(code, message)


def _relative(name):
    name = str(name).replace('\\', '/')
    path = PurePosixPath(name)
    if (not name or name.startswith('/') or any(p in ('', '.', '..') for p in name.split('/'))
            or ':' in name or '\x00' in name or any(ord(c) < 32 for c in name)):
        fail('Use an ordinary relative path inside the application.', 'IntegrityFailure')
    for part in path.parts:
        if part.rstrip(' .') != part or re.fullmatch(r'(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?', part, re.I):
            fail('An application path is not portable.', 'IntegrityFailure')
    return path.as_posix()


def _is_link(path):
    value = path.lstat()
    return stat.S_ISLNK(value.st_mode) or bool(getattr(value, 'st_file_attributes', 0) & 0x400)


def inventory(root, context, limit=DEFAULT_LIMIT):
    """Hash a bounded regular-file tree; reject links, aliases and portable-name collisions."""
    root = Path(root).resolve()
    rows, seen, total = [], set(), 0
    for directory, folders, files in os.walk(root, followlinks=False):
        context.check()
        for name in folders + files:
            path = Path(directory) / name
            if _is_link(path) or not path.resolve().is_relative_to(root):
                fail('Application links and reparse points are not imported.', 'IntegrityFailure')
            relative = _relative(path.relative_to(root).as_posix())
            key = relative.casefold()
            if key in seen:
                fail('Application paths collide on a case-insensitive filesystem.', 'IntegrityFailure')
            seen.add(key)
        for name in sorted(files):
            path = Path(directory) / name
            if not stat.S_ISREG(path.stat().st_mode):
                fail('Only regular application files can be imported.', 'IntegrityFailure')
            total += path.stat().st_size
            if total > limit or len(rows) >= FILE_LIMIT:
                fail('The application exceeds the configured file or byte limit.', 'ResourceLimit')
            rows.append({'path': path.relative_to(root).as_posix(), 'size': path.stat().st_size,
                         'sha256': sha256_file(path, context.cancellation)})
    return sorted(rows, key=lambda row: row['path'])


def copy_tree(source, target, context, limit=DEFAULT_LIMIT, expected=None):
    source, target = Path(source).resolve(), Path(target).resolve()
    if target == source or target.is_relative_to(source) or source.is_relative_to(target):
        fail('Use a separate application output directory.', 'AccessDenied')
    rows = inventory(source, context, limit)
    if expected is not None and rows != expected:
        fail('The saved application changed. Import or convert it again.', 'Conflict')
    target.mkdir(parents=True, exist_ok=False)
    if shutil.disk_usage(target).free < sum(row['size'] for row in rows):
        fail('Not enough free space for the application snapshot.', 'ResourceLimit')
    for row in rows:
        context.check()
        destination = target / row['path']
        destination.parent.mkdir(parents=True, exist_ok=True)
        with (source / row['path']).open('rb') as reader, destination.open('xb') as writer:
            for block in iter(lambda: reader.read(1 << 20), b''):
                context.check()
                writer.write(block)
        if sha256_file(destination, context.cancellation) != row['sha256']:
            fail('Application changed while copying.', 'Conflict')
        shutil.copymode(source / row['path'], destination)
    if inventory(source, context, limit) != rows:
        fail('Application changed while copying.', 'Conflict')
    return rows


def _copy_file(source, destination, context):
    """Large containers must remain cancellable while making the private copy."""
    before=source.stat()
    if shutil.disk_usage(destination.parent).free<before.st_size:
        fail('Not enough free space for the private input copy.', 'ResourceLimit')
    digest=hashlib.sha256()
    with source.open('rb') as reader,destination.open('xb') as writer:
        for block in iter(lambda:reader.read(1<<20),b''):
            context.check()
            digest.update(block)
            writer.write(block)
    after=source.stat()
    if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):
        fail('Application input changed while copying.', 'Conflict')
    return {'sha256':digest.hexdigest(),'size':before.st_size}


def _unzip(source, destination, context, limit):
    with zipfile.ZipFile(source) as archive:
        items, seen, total = [], set(), 0
        for item in archive.infolist():
            context.check()
            name = item.filename.replace('\\', '/').rstrip('/')
            if not name:
                continue
            relative = _relative(name)
            if relative.casefold() in seen:
                fail('Archive paths collide.', 'IntegrityFailure')
            seen.add(relative.casefold())
            mode = item.external_attr >> 16
            if stat.S_ISLNK(mode) or (stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR)):
                fail('Archive links and special files are not supported.', 'IntegrityFailure')
            if item.flag_bits & 1:
                fail('Extract the password-protected archive before importing it.', 'Unsupported')
            total += item.file_size
            if total > limit or len(items) >= FILE_LIMIT:
                fail('Archive expansion exceeds the configured limit.', 'ResourceLimit')
            items.append((item, relative))
        destination.mkdir(parents=True, exist_ok=False)
        written = 0
        for item, name in items:
            target = destination / name
            if item.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(item) as reader, target.open('xb') as writer:
                for block in iter(lambda: reader.read(1 << 20), b''):
                    context.check()
                    written += len(block)
                    if written > limit:
                        fail('Archive expansion exceeds the configured limit.', 'ResourceLimit')
                    writer.write(block)


def elf_info(path, require_entry=True):
    """Read ELF64 program headers without executing or loading the application."""
    path = Path(path)
    size = path.stat().st_size
    with path.open('rb') as handle:
        header = handle.read(64)
        if len(header) != 64 or header[:6] != b'\x7fELF\x02\x01':
            fail('Porting requires a little-endian ELF64 executable.', 'Unsupported')
        kind, machine = struct.unpack_from('<HH', header, 16)
        entry, phoff = struct.unpack_from('<QQ', header, 24)
        width, count = struct.unpack_from('<HH', header, 54)
        if machine != 62 or width != 56 or not 0 < count <= 4096 or phoff + count * width > size:
            fail('Invalid or unsupported x86-64 ELF program headers.', 'Unsupported')
        handle.seek(phoff)
        table = handle.read(count * width)
        segments = []
        for index in range(count):
            ptype, flags, offset, address, _, length, memory, alignment = struct.unpack_from('<IIQQQQQQ', table, index * width)
            if (length and offset + length > size) or (ptype == 1 and memory < length) or (alignment and alignment & (alignment - 1)):
                fail('ELF segment ranges or alignment are invalid.', 'IntegrityFailure')
            if ptype == 1 and alignment > 1 and address % alignment != offset % alignment:
                fail('ELF load alignment is invalid.', 'IntegrityFailure')
            segments.append({'index':index, 'type':ptype, 'flags':flags, 'offset':offset,
                             'address':address, 'fileSize':length, 'memorySize':memory, 'alignment':alignment})
        if require_entry and not any(s['type']==1 and s['flags'] & 1 and s['address'] <= entry < s['address']+s['memorySize'] for s in segments):
            fail('ELF entry point is outside its executable load segments.', 'IntegrityFailure')
        handle.seek(0)
        sample = handle.read(min(size, 16 * 1024**2))
    # These are string candidates, not confirmed imports or a compatibility score.
    libraries = sorted({s.decode('ascii') for s in re.findall(rb'lib[A-Za-z0-9_+.-]{1,100}\.(?:prx|sprx|so)', sample)})[:500]
    return {'format':'elf', 'architecture':'x86_64', 'type':kind, 'entry':hex(entry),
            'segments':segments, 'libraryCandidates':libraries,
            'hasConsoleDynamicData':any(s['type']==0x61000000 for s in segments)}


def unwrap_self(source, destination, context):
    """Reassemble explicitly mapped plaintext SELF segments; no keys or decryption."""
    source, destination = Path(source), Path(destination)
    if source.stat().st_size > 512 * 1024**2:
        fail('This SELF exceeds the supported preparation limit.', 'ResourceLimit')
    data = source.read_bytes()
    if not data.startswith(SELF_MAGICS):
        fail('The file is not a supported SELF container.', 'Unsupported')
    inner = data.find(b'\x7fELF\x02\x01', 0x20, min(len(data), 1024*1024))
    if inner < 0 or inner + 64 > len(data):
        fail('SELF has no readable ELF header; provide a decrypted ELF.', 'Unsupported')
    header = bytearray(data[inner:inner+64])
    phoff = struct.unpack_from('<Q', header, 32)[0]
    width, count = struct.unpack_from('<HH', header, 54)
    if width != 56 or not 0 < count <= 4096 or inner+phoff+width*count > len(data):
        fail('SELF program headers are invalid.', 'IntegrityFailure')
    table = bytearray(data[inner+phoff:inner+phoff+width*count])
    records = {}
    for pos in range(0x20, inner-31, 32):
        flags, offset, stored, plain = struct.unpack_from('<QQQQ', data, pos)
        index = flags >> 20
        if not flags & 0x800 or index >= count:
            continue
        # Kernel fake-SELF containers can retain the encrypted metadata bit
        # while storing plaintext. We never transform encrypted payloads.
        encrypted=bool(flags & 2) and data.startswith(SELF_MAGIC)
        if index in records or flags & 8 or encrypted or stored != plain or offset < inner+64 or offset+stored > len(data):
            fail('SELF segments are compressed, ambiguous or truncated. Supply a decrypted ELF.', 'Unsupported')
        records[index] = (offset, stored)
    regions, maximum = [], phoff + len(table)
    omitted_metadata=[]
    for index in range(count):
        context.check()
        values = struct.unpack_from('<IIQQQQQQ', table, index*56)
        ptype, flags, offset, address, _, length, memory, alignment = values
        if not length:
            continue
        if index in records and records[index][1] == length:
            start, _ = records[index]
        else:
            # Dynamic program headers may describe a subrange of a mapped load
            # segment instead of having their own SELF storage record.
            containers=[]
            for mapped,(stored_offset,stored_length) in records.items():
                parent=struct.unpack_from('<IIQQQQQQ',table,mapped*56)
                if stored_length==parent[5] and parent[2]<=offset and offset+length<=parent[2]+parent[5]:
                    containers.append(stored_offset+offset-parent[2])
            if not containers and ptype in (4,0x6fffff00,0x6fffff01):
                # Notes/version/comment payloads can be absent from a SELF. They
                # are not loadable code or dynamic-link data. Explicitly omit
                # only these metadata payloads instead of guessing trailing bytes.
                omitted_metadata.append({'index':index,'type':hex(ptype),'reason':'No explicit readable segment mapping.'})
                struct.pack_into('<Q',table,index*56+8,0)
                struct.pack_into('<QQ',table,index*56+32,0,0)
                continue
            if not containers or any(data[s:s+length]!=data[containers[0]:containers[0]+length] for s in containers):
                fail('SELF segment mapping is incomplete. Supply a decrypted ELF.', 'Unsupported')
            start=containers[0]
        segment = data[start:start+length]
        if ptype == 1 and flags & 1 and len(segment) >= 4096:
            sample = segment[:65536]
            entropy = -sum((n/len(sample))*math.log2(n/len(sample)) for n in Counter(sample).values())
            if entropy > 7.8:
                fail('SELF executable data appears encrypted. No decryption is performed.', 'Unsupported')
        if offset+length > 1024**3 or (ptype == 1 and memory < length):
            fail('SELF output ranges exceed the supported limit.', 'IntegrityFailure')
        for previous, previous_data in regions:
            lo, hi = max(offset,previous), min(offset+length,previous+len(previous_data))
            if hi > lo and segment[lo-offset:hi-offset] != previous_data[lo-previous:hi-previous]:
                fail('SELF segment ranges disagree.', 'IntegrityFailure')
        regions.append((offset,segment))
        maximum = max(maximum,offset+length)
    # SELF images need not contain a reusable section table. Program headers remain authoritative.
    struct.pack_into('<Q', header, 40, 0)
    struct.pack_into('<HHH', header, 58, 0, 0, 0)
    with destination.open('xb') as output:
        output.truncate(maximum)
        for offset, segment in regions:
            context.check()
            output.seek(offset)
            output.write(segment)
        output.seek(0)
        output.write(header)
        output.seek(phoff)
        output.write(table)
    return dict(elf_info(destination, require_entry=False),omittedMetadata=omitted_metadata)


def tools(updates=None):
    config = read_json(TOOLS_FILE, {})
    if updates is not None:
        unknown = set(updates)-set(TOOL_FIELDS)
        if unknown:
            fail('Unknown porting tool setting.')
        for key,value in updates.items():
            if value:
                path = Path(value).expanduser()
                if not path.is_absolute() or not path.exists():
                    fail('Choose an existing absolute tool or library path.')
                if key.endswith('Libraries') != path.is_dir():
                    fail('Choose a library folder or a tool file as appropriate.')
                config[key] = str(path.resolve())
            else:
                config.pop(key,None)
        write_json(TOOLS_FILE,config)
    return {'settings':config, 'available':{key:bool(config.get(key) and Path(config[key]).exists()) for key in TOOL_FIELDS},
            'anyps5Source':'https://github.com/boykopovar/AnyPS5',
            'ultrapackSource':'https://github.com/knutwurst/ps5-ultrapack'}


def _extract(source, destination, context, limit):
    config = tools()['settings']
    cli = config.get('ultrapackCli','')
    if not cli or not Path(cli).is_file():
        fail('Configure the PS5 UltraPack backend/cli.py to open this container, or import an extracted folder.', 'MissingDependency')
    temporary=destination.parent/'temp'
    temporary.mkdir()
    command = [config.get('ultrapackPython') or sys.executable, cli, str(source), str(destination),
               '--temp-dir',str(temporary),'--to','folder']
    last_check = 0
    def check_expansion(_process):
        nonlocal last_check
        if time.monotonic()-last_check < 1: return
        last_check = time.monotonic()
        total = count = 0
        for directory, folders, files in os.walk(destination.parent, followlinks=False):
            context.check()
            for name in folders+files:
                path = Path(directory)/name
                try:
                    if _is_link(path): fail('Extraction produced a link or reparse point.', 'IntegrityFailure')
                    if path.is_file() and path!=source: total += path.stat().st_size; count += 1
                except FileNotFoundError:
                    # UltraPack moves/removes its private staging tree while
                    # extracting. The completed app tree is validated separately.
                    continue
                if total > limit or count > FILE_LIMIT:
                    fail('Extracted application exceeds the configured limit.', 'ResourceLimit')
    environment = {'PS5_FFPFSC_APP_DIR':str(Path(context.workdir)/'ultrapack-profile'),
                   'PYTHONDONTWRITEBYTECODE':'1',
                   'FFPFSC_PKG_TOOL':config.get('ultrapackPkgTool')}
    code, out, err = process.run(command, context=context, cwd=Path(context.workdir), timeout=3600,
        env=environment, on_tick=check_expansion,
        log_name='ultrapack-extract', own_children=True, output_limit=2*1024**2, preserve_output=True)
    if code:
        fail('UltraPack extraction failed:\n'+(out+'\n'+err)[-8000:], 'EngineFailed')
    if not destination.is_dir():
        fail('UltraPack did not produce an extracted application folder.', 'EngineFailed')


def _id(value):
    if not re.fullmatch('[a-f0-9]{32}',str(value)):
        fail('Use an identifier returned by the porting workflow.')
    return value


def info(project, import_id=''):
    if not import_id:
        import_id = read_json(project.dir/'porting/latest.json',{}).get('importId','')
    if not import_id:
        return {'projectId':project.id,'available':False}
    record = read_json(project.dir/'porting/imports'/_id(import_id)/'import.json',None)
    if not record:
        fail('The imported application is unavailable.', 'NotFound')
    return dict(record,available=True)


def open_input(store, source, context, entry='', original='', limit=DEFAULT_LIMIT):
    source = Path(source).expanduser()
    if not source.is_absolute() or not source.exists():
        fail('Choose an existing application file or directory.')
    source = source.resolve()
    limit = min(1024**4,max(1024,int(limit)))
    work = Path(context.workdir)/('porting-import-'+uuid.uuid4().hex)
    work.mkdir(parents=True)
    app = work/'app0'
    container=None
    context.progress(2,'Preparing application input')
    if source.is_dir():
        copy_tree(source,app,context,limit)
    elif source.suffix.lower() not in IMAGE_SUFFIXES and zipfile.is_zipfile(source):
        _unzip(source,app,context,limit)
    elif source.suffix.lower() in IMAGE_SUFFIXES:
        if source.stat().st_size > limit:
            fail('Container exceeds the configured byte limit.', 'ResourceLimit')
        local = work/source.name
        container=_copy_file(source,local,context)
        _extract(local,app,context,limit)
        inventory(app,context,limit)
        # The prepared tree plus the recorded container digest are persistent;
        # the SDK already owns the staged container until task cleanup.
        local.unlink()
    else:
        if source.stat().st_size > limit:
            fail('Executable exceeds the configured byte limit.', 'ResourceLimit')
        app.mkdir()
        _copy_file(source,app/source.name,context)
    rows = inventory(app,context,limit)
    originals = work/'original-self'
    unwrapped=[]
    unprepared=[]
    for row in rows:
        path = app/row['path']
        with path.open('rb') as handle: magic=handle.read(6)
        if magic.startswith(SELF_MAGICS):
            saved = originals/row['path']
            saved.parent.mkdir(parents=True,exist_ok=True)
            _copy_file(path,saved,context)
            prepared=path.with_name(path.name+'.cydec-elf')
            try:
                preparation=unwrap_self(path,prepared,context)
            except CyToolError as error:
                # Opaque signed metadata (for example sce_sys/about/right.sprx)
                # is a resource, not a guest runtime module. Keep its bytes and
                # report the unknown; executable/module directories still fail.
                if error.code!='Unsupported' or 'sce_sys' not in Path(row['path']).parts or row['path']==entry:
                    raise
                if prepared.exists():prepared.unlink()
                unprepared.append({'path':row['path'],'reason':str(error)})
                continue
            os.replace(prepared,path)
            unwrapped.append({'path':row['path'],'sourceSha256':row['sha256'],
                              'omittedMetadata':preparation['omittedMetadata']})
    rows=inventory(app,context,limit)
    candidates=[]
    for row in rows:
        path=app/row['path']
        with path.open('rb') as handle: magic=handle.read(6)
        if magic==b'\x7fELF\x02\x01': candidates.append(row['path'])
    if entry:
        selected=_relative(entry)
        if selected not in candidates: fail('Selected entry is not an ELF64 executable.')
    else:
        named=[c for c in candidates if Path(c).name.casefold() in ('eboot.bin','eboot.elf')]
        chosen=named or candidates
        if len(chosen)!=1:
            fail('Select one application entry using its relative path. Candidates: '+', '.join(chosen[:30]), 'AmbiguousInput')
        selected=chosen[0]
    description=elf_info(app/selected)
    application_root=(app/selected).parent
    metadata=application_root/'sce_sys/param.json'
    title={}
    if metadata.is_file():
        if metadata.stat().st_size>1024**2: fail('Application metadata is too large.', 'ResourceLimit')
        try:
            value=json.loads(metadata.read_text('utf-8-sig'))
            title={key:value.get(key) for key in ('titleId','contentId','contentVersion','requiredSystemSoftwareVersion')}
            localized=value.get('localizedParameters',{})
            names=localized.get(localized.get('defaultLanguage',value.get('defaultLanguage','en-US')),{})
            title['name']=str(names.get('titleName',''))[:512]
        except (ValueError,AttributeError,TypeError):
            fail('Application param.json is invalid.', 'IntegrityFailure')
    project,_=store.open(app/selected,source_path=str(original or source),cancellation=context.cancellation)
    import_id=uuid.uuid4().hex
    final=project.dir/'porting/imports'/import_id
    final.parent.mkdir(parents=True,exist_ok=True)
    context.check()
    shutil.move(str(work),str(final))
    record={'projectId':project.id,'importId':import_id,'status':'prepared','source':str(original or source),
            'directory':str(final/'app0'),'entry':selected,'applicationRoot':str(application_root.relative_to(app)),
            'container':container,
            'executables':candidates,
            'title':title,'elf':description,'files':rows,'unwrapped':unwrapped,'unpreparedSelf':unprepared,
            'maxBytes':limit,'createdAt':time.time(),
            'limits':['No decryption is performed.','Library strings are candidates, not verified imports.',
                      'Prepared input is not an executable desktop port.']}
    write_json(final/'import.json',record)
    write_json(project.dir/'porting/latest.json',{'importId':import_id})
    context.progress(100,'Application input prepared')
    return dict(record,available=True)


def plan(project, target, import_id=''):
    if target not in ('windows','linux'):
        fail('Choose Windows or Linux.')
    imported=info(project,import_id)
    if not imported.get('available'):
        fail('Import an application before planning a port.', 'NotFound')
    config=tools()
    blockers=[]
    for key,message in [('relinker','Configure or install the AnyPS5 converter.'),
                        (target+'Libraries','Configure the compatibility libraries for the selected target.')]:
        if not config['available'][key]: blockers.append({'code':key,'message':message})
    return {'projectId':project.id,'importId':imported['importId'],'target':target,
            'backend':'anyps5-external','status':'blocked' if blockers else 'ready', 'blockers':blockers,
            'input':imported['elf'],'limits':imported['limits']+[
                'Console API and GPU compatibility are supplied by the selected external backend.',
                'Conversion does not prove that an application or game works.']}


def _save_attempt(project, report):
    report.setdefault('attemptId',uuid.uuid4().hex)
    write_json(project.dir/'porting/attempts'/(report['attemptId']+'.json'),report)
    write_json(project.dir/'porting/latest-attempt.json',{'attemptId':report['attemptId']})


def _converter_inputs(imported,target,context):
    """The relinker reads executables/modules and metadata, not game assets.

    Resources are copied once to the output app0 tree separately and retain the
    full manifest checks. No links to the original or prepared tree are created.
    """
    root=Path(imported['directory'])
    target.mkdir()
    executables=set(imported.get('executables',[imported['entry']]))
    for row in imported['files']:
        relative=Path(row['path'])
        if ('executables' in imported and row['path'] not in executables and 'sce_sys' not in relative.parts
                and relative.suffix.lower() not in ('.prx','.sprx','.elf')):continue
        context.check()
        source=root/relative
        if _is_link(source) or not source.resolve().is_relative_to(root.resolve()):
            fail('Prepared converter input was redirected.','IntegrityFailure')
        destination=target/relative
        destination.parent.mkdir(parents=True,exist_ok=True)
        copied=_copy_file(source,destination,context)
        if copied['sha256']!=row['sha256'] or copied['size']!=row['size']:
            fail('Prepared converter input changed. Import it again.','Conflict')


def convert(project, target, context, import_id='', to_intel=False, standalone=False,
            diagnostics=False, trace_imports=False, analyze_on_failure=True):
    with project.lock:
        if target!='windows' and (diagnostics or trace_imports):
            fail('AnyPS5 startup diagnostics and import tracing require Windows output.')
        imported=info(project,import_id)
        ready=plan(project,target,imported['importId'])
        if ready['blockers']: return ready
        config=tools()['settings']
        work=Path(context.workdir)/('porting-convert-'+uuid.uuid4().hex)
        work.mkdir(parents=True)
        source=work/'source'
        input_limit=imported.get('maxBytes',DEFAULT_LIMIT)
        _converter_inputs(imported,source,context)
        output=work/'output'
        output.mkdir()
        copy_tree(config[target+'Libraries'],output/'libs',context)
        local_app=source/Path(imported['entry']).parent
        secondary=[]
        loose_modules=[]
        for candidate in sorted(local_app.iterdir()):
            if not candidate.is_file() or candidate==source/imported['entry']:continue
            with candidate.open('rb') as stream:magic=stream.read(6)
            if magic!=b'\x7fELF\x02\x01':continue
            kind=elf_info(candidate,require_entry=False)['type']
            if kind in (2,0xfe00,0xfe04,0xfe10):secondary.append(candidate.name)
            elif kind in (3,0xfe18):loose_modules.append(candidate.name)
            else:fail('Unsupported ELF type beside the entry executable: '+candidate.name,'Unsupported')
        if secondary and loose_modules:
            fail('The converter cannot combine secondary root executables and loose root modules in the same module directory. Use explicit module folders.','Unsupported')
        app_relative=Path(imported['entry']).parent
        app_rows=[dict(row,path=Path(row['path']).relative_to(app_relative).as_posix())
                  for row in imported['files'] if Path(row['path']).is_relative_to(app_relative)]
        copy_tree(Path(imported['directory'])/app_relative,output/'app0',context,limit=input_limit,expected=app_rows)
        executable=output/('application.exe' if target=='windows' else 'application.elf')
        relinker=Path(config['relinker'])
        tool_hash=sha256_file(relinker,context.cancellation)
        help_code,help_out,help_err=process.run([str(relinker),'--help'],context=context,cwd=output,
            timeout=30,log_name='anyps5-capabilities',own_children=True,output_limit=128*1024)
        capabilities=set(re.findall(r'--[a-z][a-z-]*',help_out+'\n'+help_err))
        required={'--registry','--sce-module-path'}
        if loose_modules:required.add('--module-dir')
        if secondary:required.add('--executable')
        if target=='windows':required.add('--windows')
        if to_intel:required.add('--to-intel')
        if standalone:required={'--registry','--skip-sce-module'}|({'--windows'} if target=='windows' else set())|({'--to-intel'} if to_intel else set())
        if diagnostics:required.add('--windows-diagnostics')
        if trace_imports:required.add('--trace-imports')
        if help_code or not required<=capabilities:
            fail('The selected converter does not expose the required command-line options.', 'Unsupported')
        # Older published versions predate --no-patches. Never discover patches from input data.
        auto_patch=local_app/'relinker-patches.toml'
        if auto_patch.is_file(): shutil.move(str(auto_patch),str(work/'disabled-relinker-patches.toml'))
        command=[str(relinker)]
        if target=='windows': command.append('--windows')
        if to_intel: command.append('--to-intel')
        if diagnostics:command.append('--windows-diagnostics')
        if trace_imports:command.append('--trace-imports')
        if '--no-patches' in capabilities:command.append('--no-patches')
        command.append('--registry')
        if standalone:
            for row in inventory(local_app,context,limit=input_limit):
                candidate=local_app/row['path']
                if candidate==source/imported['entry']:continue
                with candidate.open('rb') as handle:magic=handle.read(4)
                if magic in (b'\x7fELF',*SELF_MAGICS) or candidate.suffix.lower() in ('.prx','.sprx'):
                    fail('Standalone mode cannot omit bundled executable modules.', 'InvalidParameters')
            command.append('--skip-sce-module')
        else:
            command+=['--sce-module-path',str(local_app)]
            if loose_modules:command+=['--module-dir','.']
            for other in secondary:command+=['--executable',other]
        command += [str(source/imported['entry']),str(executable)]
        context.progress(15,'Converting executable')
        code,out,err=process.run(command,context=context,cwd=output,timeout=1800,log_name='anyps5-convert',
            own_children=True,output_limit=4*1024**2,preserve_output=True)
        report={'projectId':project.id,'importId':imported['importId'],'target':target,
                'backend':'anyps5-external','toolSha256':tool_hash,'converterCapabilities':sorted(capabilities),
                'output':(out+'\n'+err)[-200000:],
                'exitCode':code,'status':'conversion-failed','limits':ready['limits'],
                'options':{'toIntel':to_intel,'standalone':standalone,'diagnostics':diagnostics,'traceImports':trace_imports},
                'secondaryExecutables':secondary,'looseModules':loose_modules,
                'createdAt':time.time()}
        if standalone:report['limits'].append('Guest module conversion was explicitly disabled for a standalone application.')
        _save_attempt(project,report)
        if code:
            if analyze_on_failure:
                try:
                    from . import porting_analysis
                    diagnosis=porting_analysis.diagnose(project,context,attempt_id=report['attemptId'],max_functions=32)
                    diagnosis['findings']=sorted(diagnosis['findings'],key=lambda r:r['severity']!='error')[:50]
                    report['diagnosis']=diagnosis
                except Exception as error:
                    if getattr(error,'code','') in ('Cancelled','Timeout'):raise
                    context.check()
                    report['diagnosisError']={'code':getattr(error,'code',type(error).__name__),'message':str(error)}
                _save_attempt(project,report)
            return report
        if sha256_file(relinker,context.cancellation)!=tool_hash:
            fail('The converter changed while running.', 'Conflict')
        if inventory(imported['directory'],context,limit=input_limit)!=imported['files']:
            fail('The imported application changed while converting.', 'Conflict')
        from .detect import detect
        fmt=detect(executable) if executable.is_file() else {}
        if fmt.get('format') != ('pe' if target=='windows' else 'elf') or fmt.get('arch')!='x86_64':
            fail('The converter did not produce the requested executable format.', 'EngineFailed')
        additional=[]
        for other in secondary:
            name=other+executable.suffix
            extra=output/name
            fmt=detect(extra) if extra.is_file() else {}
            if fmt.get('format')!=('pe' if target=='windows' else 'elf') or fmt.get('arch')!='x86_64':
                fail('The converter did not produce the secondary executable: '+name,'EngineFailed')
            additional.append({'source':str(Path(imported['entry']).parent/other).replace('\\','/'),'executable':name})
        receipt=uuid.uuid4().hex
        final=project.dir/'porting/conversions'/receipt
        final.parent.mkdir(parents=True,exist_ok=True)
        output_limit=input_limit+DEFAULT_LIMIT
        files=inventory(output,context,limit=output_limit)
        if output.stat().st_dev==final.parent.stat().st_dev:
            # The validated output is job-owned. Atomic persistence avoids a
            # second full asset copy on the same volume; originals stay separate.
            if final.exists():fail('Conversion output already exists.','Conflict')
            os.replace(output,final)
        else:
            copy_tree(output,final,context,limit=output_limit,expected=files)
        report.update(conversionId=receipt,status='converted-unverified',directory=str(final),
                      executable=executable.name,additionalExecutables=additional,files=files,maxBytes=output_limit,createdAt=time.time())
        registry_sources={executable.stem+'.registry.json':imported['entry'],
                          **{Path(e['executable']).stem+'.registry.json':e['source'] for e in additional}}
        report['registries']=[{'path':row['path'],'source':registry_sources.get(row['path'])}
                              for row in files if row['path'].endswith('.registry.json')]
        # The receipt lives outside the hashed output tree.
        write_json(final.parent/(receipt+'.json'),report)
        write_json(project.dir/'porting/latest-conversion.json',{'conversionId':receipt})
        _save_attempt(project,report)
        context.progress(100,'Conversion complete; behavior unverified')
        return report


def conversion(project, conversion_id=''):
    if not conversion_id:
        conversion_id=read_json(project.dir/'porting/latest-conversion.json',{}).get('conversionId','')
    if not conversion_id: return {'projectId':project.id,'available':False}
    result=read_json(project.dir/'porting/conversions'/(_id(conversion_id)+'.json'),None)
    if not result: fail('The converted application is unavailable.', 'NotFound')
    return dict(result,available=True)


def run(project, context, conversion_id='', scenarios=None, timeout=60, trace_libraries=''):
    with project.lock:
        record=conversion(project,conversion_id)
        if not record.get('available'): fail('Convert the application before running it.', 'NotFound')
        host='windows' if os.name=='nt' else ('linux' if sys.platform.startswith('linux') else sys.platform)
        if record['target']!=host or platform.machine().lower() not in ('amd64','x86_64'):
            fail('The converted application requires the matching x86-64 host operating system.', 'Unsupported')
        if trace_libraries and (not re.fullmatch(r'all|lib[A-Za-z0-9_.-]+(?:,lib[A-Za-z0-9_.-]+)*',trace_libraries)
                                or len(trace_libraries)>1024):
            fail('Trace libraries must be all or comma-separated library names.')
        if trace_libraries and not record.get('options',{}).get('traceImports'):
            fail('Convert with traceImports=true before enabling import tracing.', 'Unsupported')
        cases=scenarios if scenarios is not None else [{}]
        if not isinstance(cases,list) or not 1<=len(cases)<=20: fail('Supply one to twenty test scenarios.')
        assertions=all(isinstance(c,dict) and ('expectedExitCode' in c or 'expectedStdout' in c) for c in cases)
        results=[]
        for index,case in enumerate(cases):
            if not isinstance(case,dict) or set(case)-{'arguments','stdin','expectedExitCode','expectedStdout'}:
                fail('Scenario fields: arguments, stdin, expectedExitCode, expectedStdout.')
            arguments=case.get('arguments',[])
            if not isinstance(arguments,list) or len(arguments)>100 or not all(isinstance(a,str) and len(a)<=4096 and '\x00' not in a for a in arguments):
                fail('Scenario arguments must be a bounded string array.')
            if not isinstance(case.get('stdin',''),str) or len(case.get('stdin',''))>1024**2: fail('Scenario stdin is too large.')
            if 'expectedExitCode' in case and type(case['expectedExitCode']) is not int: fail('Expected exit code must be an integer.')
            if 'expectedStdout' in case and (not isinstance(case['expectedStdout'],str) or len(case['expectedStdout'])>1024**2): fail('Expected output must be bounded text.')
            # Runtime workspaces already contain client/job UUIDs. Keep executable
            # paths short enough for Windows loaders that still enforce MAX_PATH.
            root=Path(context.workdir)/('r-'+uuid.uuid4().hex[:12])
            copy_tree(record['directory'],root,context,limit=record.get('maxBytes',DEFAULT_LIMIT),expected=record['files'])
            executable=root/record['executable']
            if os.name!='nt': executable.chmod(executable.stat().st_mode|0o100)
            code,out,err=process.run([executable,*arguments],cwd=root,context=context,timeout=min(900,max(1,int(timeout))),
                stdin_text=case.get('stdin',''),log_name='porting-scenario-'+str(index),own_children=True,
                output_limit=2*1024**2,preserve_output=True,
                env={'APS5_TRACE_CALLS':trace_libraries or None,'APS5_NO_PAD_INPUT':None})
            passed=(('expectedExitCode' not in case or code==case['expectedExitCode']) and
                    ('expectedStdout' not in case or out==case['expectedStdout']))
            if 'expectedExitCode' not in case and 'expectedStdout' not in case: passed=passed and code==0
            results.append({'index':index,'exitCode':code,'stdout':out,'stderr':err,'passed':passed,'assertions':case})
        status=('scenarios-passed' if assertions else 'executed-unverified') if all(r['passed'] for r in results) else 'execution-failed'
        result={'projectId':project.id,'conversionId':record['conversionId'],'status':status,'scenarios':results,
                'runId':uuid.uuid4().hex,'traceLibraries':trace_libraries,
                'limits':['A successful launch is not proof of graphical or behavioral equivalence.',
                          'These assertions cover only the supplied finite scenarios.']}
        write_json(project.dir/'porting/runs'/(result['runId']+'.json'),result)
        write_json(project.dir/'porting/latest-run.json',{'runId':result['runId']})
        return result


def install_anyps5(target,context):
    if target not in ('windows','linux'): fail('Choose Windows or Linux.')
    if platform.machine().lower() not in ('amd64','x86_64'): fail('The prebuilt converter requires an x86-64 host.', 'Unsupported')
    if os.name!='nt' and not sys.platform.startswith('linux'): fail('Official converter installation supports Windows and Linux hosts.', 'Unsupported')
    host='windows' if os.name=='nt' else 'linux'
    release=components._http_json('https://api.github.com/repos/boykopovar/AnyPS5/releases/latest')
    tag=release['tag_name']
    if not re.fullmatch(r'v[0-9][0-9A-Za-z._-]*',tag): fail('Unexpected AnyPS5 release identifier.', 'IntegrityFailure')
    names=['relinker-'+tag+('.exe' if host=='windows' else ''), 'prx-'+target+'-'+tag+'.zip']
    selected=[]
    for name in names:
        asset=next((a for a in release['assets'] if a['name']==name),None)
        if not asset or not re.fullmatch(r'sha256:[a-fA-F0-9]{64}',asset.get('digest') or ''):
            fail('Official AnyPS5 asset or published SHA-256 is missing.', 'IntegrityFailure')
        selected.append(asset)
    final=ENGINES/'anyps5'/tag/(host+'-to-'+target)
    if final.exists():
        installed=read_json(final/'installation.json',{})
        for asset in selected:
            path=final/asset['name']
            if not path.is_file() or sha256_file(path,context.cancellation)!=asset['digest'][7:]:
                fail('Existing AnyPS5 installation differs from its release. Choose another installation.', 'IntegrityFailure')
        reference=Path(context.workdir)/('anyps5-reference-'+uuid.uuid4().hex)
        components.extract(final/names[1],reference,context)
        relative=_relative(installed.get('libraries',''))
        reference_lib=reference/Path(relative).relative_to('libraries')
        if inventory(reference_lib,context)!=inventory(final/relative,context):
            fail('Installed compatibility libraries differ from the verified release.', 'IntegrityFailure')
    else:
        from cytools_core.downloads import DownloadManager
        manager=DownloadManager(DOWNLOADS/'anyps5',timeout=120,use_shared_cache=False)
        stage=Path(context.workdir)/('anyps5-install-'+uuid.uuid4().hex)
        stage.mkdir(parents=True)
        for asset in selected:
            context.check()
            downloaded=manager.download(asset['name'],asset['browser_download_url'],sha256=asset['digest'][7:],
                size=asset['size'],cancellation=context.cancellation)
            if downloaded.get('state')!='Completed': fail('AnyPS5 download did not finish.', 'DownloadFailed')
            path=Path(downloaded['path'])
            shutil.copyfile(path,stage/asset['name'])
        components.extract(stage/names[1],stage/'libraries',context)
        candidates=list((stage/'libraries').rglob('libc.prx'))
        if len(candidates)!=1: fail('Cannot locate the AnyPS5 compatibility libraries.', 'IntegrityFailure')
        relative=str(candidates[0].parent.relative_to(stage))
        write_json(stage/'installation.json',{'tag':tag,'target':target,'libraries':relative,
            'assets':[{'name':a['name'],'sha256':a['digest'][7:]} for a in selected]})
        final.parent.mkdir(parents=True,exist_ok=True)
        shutil.move(str(stage),str(final))
        installed=read_json(final/'installation.json',{})
    relinker=final/names[0]
    if os.name!='nt': relinker.chmod(relinker.stat().st_mode|0o100)
    return tools({'relinker':str(relinker),target+'Libraries':str(final/installed['libraries'])})


def install_ultrapack(context, build_pkg_helper=True):
    """Official source checkout in a private engine, never in the Tool's Python."""
    if os.name!='nt' and not sys.platform.startswith('linux'):
        fail('Automatic UltraPack installation supports Windows and Linux. Configure another backend explicitly.', 'Unsupported')
    from cytools_core.downloads import DownloadManager
    revision=components._http_json('https://api.github.com/repos/knutwurst/ps5-ultrapack/commits/main')['sha']
    if not re.fullmatch('[a-f0-9]{40}',revision): fail('Unexpected UltraPack source revision.', 'IntegrityFailure')
    final=ENGINES/'ultrapack'/revision
    marker=final/'installation.json'
    installed=read_json(marker,{})
    if installed:
        source_files=lambda:[row for row in inventory(final/'source',context)
                             if '__pycache__' not in Path(row['path']).parts and not row['path'].endswith('.pyc')]
        if source_files()!=installed['sourceFiles']:
            fail('Installed UltraPack source changed. Use a clean engine installation.', 'IntegrityFailure')
    else:
        manager=DownloadManager(DOWNLOADS/'ultrapack',timeout=120,use_shared_cache=False)
        downloaded=manager.download('ultrapack-'+revision+'.zip',
            'https://codeload.github.com/knutwurst/ps5-ultrapack/zip/'+revision,cancellation=context.cancellation)
        if downloaded.get('state')!='Completed':fail('UltraPack source download did not finish.', 'DownloadFailed')
        stage=Path(context.workdir)/('ultrapack-install-'+uuid.uuid4().hex)
        components.extract(Path(downloaded['path']),stage,context)
        sources=list(stage.glob('*/backend/cli.py'))
        if len(sources)!=1:fail('Cannot locate the official UltraPack backend.', 'IntegrityFailure')
        final.mkdir(parents=True,exist_ok=True)
        if (final/'source').exists():
            existing=[row for row in inventory(final/'source',context)
                      if '__pycache__' not in Path(row['path']).parts and not row['path'].endswith('.pyc')]
            if existing!=inventory(sources[0].parents[1],context):
                fail('Incomplete UltraPack source differs from the official archive.', 'IntegrityFailure')
        else:shutil.move(str(sources[0].parents[1]),str(final/'source'))
    python=final/'venv'/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
    if not python.is_file():
        code,out,err=process.run([sys.executable,'-m','venv',str(final/'venv')],context=context,
            timeout=120,own_children=True,log_name='ultrapack-venv')
        if code:fail('Cannot create the private UltraPack Python environment.\n'+err[-4000:],'MissingDependency')
    if not installed:
        context.progress(35,'Installing private UltraPack dependencies')
        code,out,err=process.run([python,'-m','pip','install','--disable-pip-version-check',
            'cryptography>=41','py7zr>=0.22','rarfile>=4','psutil>=5.9'],context=context,
            timeout=600,own_children=True,log_name='ultrapack-dependencies',output_limit=1024**2)
        if code:fail('UltraPack dependency installation failed.\n'+(out+err)[-4000:],'MissingDependency')
    helper=final/'pkg-tool'/('ffpfsc-pkg-tool.exe' if os.name=='nt' else 'ffpfsc-pkg-tool')
    if installed.get('helperSha256') and (not helper.is_file() or sha256_file(helper,context.cancellation)!=installed['helperSha256']):
        fail('The installed UltraPack package helper changed.', 'IntegrityFailure')
    if build_pkg_helper and not helper.is_file():
        dotnet=shutil.which('dotnet')
        if not dotnet:fail('Building the UltraPack package helper requires .NET SDK 9 or newer. Retry with buildPkgHelper=false for PFS and archives.','MissingDependency')
        rid=('win' if os.name=='nt' else 'linux')+'-'+('x64' if platform.machine().lower() in ('amd64','x86_64') else 'arm64')
        context.progress(65,'Building the separate UltraPack package helper')
        code,out,err=process.run([dotnet,'publish',final/'source/backend/native/src/ffpfsc-pkg-tool/PkgTool.csproj',
            '-c','Release','-r',rid,'--self-contained','true','-o',str(helper.parent),
            '--artifacts-path',str(final/'build')],context=context,timeout=900,own_children=True,
            log_name='ultrapack-pkg-build',output_limit=2*1024**2)
        if code or not helper.is_file():fail('UltraPack package helper build failed.\n'+(out+err)[-6000:],'EngineFailed')
    config={'ultrapackCli':str(final/'source/backend/cli.py'),'ultrapackPython':str(python)}
    if helper.is_file():config['ultrapackPkgTool']=str(helper)
    installed={'revision':revision,'sourceFiles':[row for row in inventory(final/'source',context)
               if '__pycache__' not in Path(row['path']).parts and not row['path'].endswith('.pyc')],
               'archiveSha256':sha256_file(downloaded['path'],context.cancellation) if not installed else installed.get('archiveSha256'),
               'helperSha256':sha256_file(helper,context.cancellation) if helper.is_file() else ''}
    write_json(marker,installed)
    context.progress(100,'UltraPack backend installed')
    return dict(tools(config),revision=revision,
        limits=['Source archives do not publish an independent checksum; the resolved Git commit and local hashes are recorded.',
                'RAR may require an external unrar or 7-Zip tool. Package formats and compression depend on the installed backend.'])
