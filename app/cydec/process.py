"""Run an external engine (Ghidra, ILSpy, Vineflower, JADX...) as a cancellable subprocess.

The process tree is stopped when the job is cancelled or the timeout expires, and the
call only returns once it is really gone: a cancelled job never leaves a JVM running in
the background. Output goes to log files in the job workdir, never to our stdout.
"""
import os
import subprocess
import time
from pathlib import Path

from cytools_core import CyToolError

CREATE_NO_WINDOW = 0x08000000 if os.name == 'nt' else 0


def _kill_tree(process):
    try:
        import psutil
        parent = psutil.Process(process.pid)
        children = parent.children(recursive=True)
        for child in children:
            try:
                child.kill()
            except psutil.Error:
                pass
        parent.kill()
        psutil.wait_procs(children + [parent], timeout=10)
    except Exception:
        try:
            process.kill()
        except OSError:
            pass
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        pass


def run(command, *, context=None, cwd=None, env=None, timeout=None, log_name='process',
        on_line=None, stdin_text=None, on_output=None, protocol=None,
        output_limit=None, preserve_output=False, own_children=False,
        on_started=None, on_tick=None, stop_requested=None, on_finished=None):
    """Run `command`; return (returncode, stdout_text, stderr_text).

    `on_line(text)` receives every stdout line as it arrives (used for progress parsing).
    `on_output(stream, text)` receives stdout and stderr lines for a live console.
    """
    workdir = Path(context.workdir) if context is not None and context.workdir else None
    if workdir is not None:
        workdir.mkdir(parents=True, exist_ok=True)
    merged = dict(os.environ)
    if env:
        for key, value in env.items():
            if value is None:
                merged.pop(key, None)
            else:
                merged[key] = str(value)
    if context is not None:
        context.log('Running: ' + ' '.join(str(c) for c in command[:6])
                    + (' ...' if len(command) > 6 else ''))
    try:
        process = subprocess.Popen([str(c) for c in command], cwd=str(cwd) if cwd else None,
                                   env=merged, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   stdin=subprocess.PIPE if stdin_text is not None or protocol else subprocess.DEVNULL,
                                   creationflags=CREATE_NO_WINDOW | (0x00000004 if own_children and os.name=='nt' else 0))
    except OSError as exc:
        raise CyToolError('MissingDependency', 'Cannot start %s: %s' % (command[0], exc),
                          recoverable=True)
    import threading
    owned_job = None
    descendants = {}
    if own_children and os.name == 'nt':
        try:
            import win32api, win32job, win32process, psutil
            owned_job = win32job.CreateJobObject(None, '')
            information = win32job.QueryInformationJobObject(owned_job, win32job.JobObjectExtendedLimitInformation)
            information['BasicLimitInformation']['LimitFlags'] |= win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            win32job.SetInformationJobObject(owned_job, win32job.JobObjectExtendedLimitInformation, information)
            # Assign before the program can exit or spawn descendants. Popen owns
            # the creation handle; reopening by PID races with short-lived programs.
            win32job.AssignProcessToJobObject(owned_job, int(process._handle))
            threads=psutil.Process(process.pid).threads()
            if len(threads)!=1:raise RuntimeError('Suspended capture has no unique primary thread.')
            handle=win32api.OpenThread(0x0002,False,threads[0].id)
            try:win32process.ResumeThread(handle)
            finally:handle.Close()
        except Exception as exc:
            if owned_job:
                owned_job.Close()
            _kill_tree(process)
            raise CyToolError('MissingDependency', 'Cannot own the capture process tree: %s' % exc)
    out_lines, err_lines = [], []
    overflow = threading.Event()

    def pump(stream, sink, callback, name):
        import codecs
        decoder = codecs.getincrementaldecoder('utf-8')('replace')
        retained = 0
        reader = (lambda: stream.read1(4096)) if preserve_output or output_limit else stream.readline
        for raw in iter(reader, b''):
            if output_limit is not None:
                room = max(0, output_limit - retained)
                retained += len(raw)
                if len(raw) > room:
                    overflow.set()
                raw = raw[:room]
            text = decoder.decode(raw) if preserve_output else raw.decode('utf-8', 'replace').rstrip('\r\n')
            sink.append(text)
            if on_output is not None:
                try:
                    on_output(name, text)
                except Exception:
                    pass
            if callback is not None:
                try:
                    callback(text)
                except Exception:
                    pass
        final = decoder.decode(b'', final=True) if preserve_output else ''
        if final:
            sink.append(final)
        stream.close()

    threads = [threading.Thread(target=pump, args=(process.stderr, err_lines, None, 'stderr'), daemon=True)]
    if protocol is None:
        threads.append(threading.Thread(target=pump, args=(process.stdout, out_lines, on_line, 'stdout'), daemon=True))
    for thread in threads:
        thread.start()
    def write_stdin():
        try:
            process.stdin.write(stdin_text.encode('utf-8'))
            process.stdin.close()
        except OSError:
            pass
    if stdin_text is not None:
        writer = threading.Thread(target=write_stdin, daemon=True)
        writer.start()
        threads.append(writer)
    started = time.monotonic()
    try:
        if on_started is not None:
            on_started(process)
        if protocol is not None:
            protocol.attach(process.stdin, process.stdout)
        while process.poll() is None:
            if on_tick is not None:
                on_tick(process)
            if stop_requested is not None and stop_requested():
                _kill_tree(process)
                break
            if own_children and owned_job is None:
                try:
                    import psutil
                    for child in psutil.Process(process.pid).children(recursive=True):
                        descendants[child.pid] = child
                except Exception:
                    pass
            if overflow.is_set():
                raise CyToolError('ExecutionOutputLimit', 'Execution output exceeded the capture limit.')
            if context is not None:
                try:
                    context.check()
                except BaseException:
                    _kill_tree(process)
                    raise
            if protocol is not None:
                protocol.check()
                if protocol.finished.is_set():
                    _kill_tree(process)
                    break
            if timeout and time.monotonic() - started > timeout:
                _kill_tree(process)
                raise CyToolError('Timeout', '%s did not finish within %d seconds.'
                                  % (Path(str(command[0])).name, timeout), recoverable=True)
            time.sleep(0.1)
    except BaseException:
        _kill_tree(process)
        raise
    finally:
        if on_finished is not None:
            try:
                on_finished(process)
            except Exception:
                pass
        if owned_job is not None:
            owned_job.Close()
        for child in descendants.values():
            try:
                child.kill()
            except Exception:
                pass
        if protocol is not None:
            protocol.close()
        for thread in threads:
            thread.join(timeout=5)
        if workdir is not None:
            try:
                separator = '' if preserve_output else '\n'
                (workdir / (log_name + '.stdout.log')).write_text(separator.join(out_lines), encoding='utf-8', newline='')
                (workdir / (log_name + '.stderr.log')).write_text(separator.join(err_lines), encoding='utf-8', newline='')
            except OSError:
                pass
    if overflow.is_set():
        raise CyToolError('ExecutionOutputLimit', 'Execution output exceeded the capture limit.')
    separator = '' if preserve_output else '\n'
    return process.returncode, separator.join(out_lines), separator.join(err_lines)


def tail(text, lines=25):
    return '\n'.join(str(text).splitlines()[-lines:])
