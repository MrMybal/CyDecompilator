"""Reproducible, host-local SDK compatibility extensions; upstream stays untouched."""
import hashlib
import json
from pathlib import Path
import re
import shutil

def prepare(source,destination):
    source,destination=Path(source),Path(destination)
    paths=[source/'CMakeLists.txt',*sorted((source/'include').rglob('*')),*sorted((source/'src').rglob('*')),*sorted((source/'cmake').rglob('*')),*sorted((source/'third_party').rglob('*'))]
    stamp=hashlib.sha256(Path(__file__).read_bytes()+b''.join(p.read_bytes() for p in paths if p.is_file())).hexdigest()
    marker=destination/'.host-overlay.json'
    if marker.is_file() and json.loads(marker.read_text('utf-8'))['stamp']==stamp:return destination,json.loads(marker.read_text('utf-8'))
    destination.mkdir(parents=True,exist_ok=True)
    for directory in ('include','src','cmake','third_party'):shutil.copytree(source/directory,destination/directory,dirs_exist_ok=True)
    for name in ('CMakeLists.txt','LICENSE','README.md','README.fr.md','VERSION.md','VERSION.fr.md','THIRD_PARTY_NOTICES.md'):shutil.copy2(source/name,destination/name)
    changed=[]
    def patch(relative,before,after,count=1):
        path=destination/relative;text=path.read_text('utf-8')
        if text.count(before)!=count:raise RuntimeError('SDK compatibility extension needs review: '+relative)
        path.write_text(text.replace(before,after),'utf-8');changed.append(relative)
    path=destination/'include/cymcp/ai.hpp';text=path.read_text('utf-8')
    text,count=re.subn(r'(struct (?:HttpChatOptions|ApiOptions) \{.*?)(\n\};)',r'\1\n    std::optional<double> temperature; // Host API sampling compatibility.\2',text,flags=re.S)
    if count!=2:raise RuntimeError('SDK options layout needs review.')
    path.write_text(text,'utf-8');changed.append('include/cymcp/ai.hpp')
    patch('src/providers.cpp','options.max_output_tokens = config.settings.value("max_output_tokens", 0);','options.max_output_tokens = config.settings.value("max_output_tokens", 0);\n                        if (config.settings.contains("temperature") && !config.settings.at("temperature").is_null()) options.temperature = config.settings.at("temperature").get<double>();',2)
    patch('src/ai.cpp','        if (options_.max_output_tokens > 0)\n            payload["max_tokens"] = options_.max_output_tokens;','        if (options_.max_output_tokens > 0)\n            payload["max_tokens"] = options_.max_output_tokens;\n        if (options_.temperature) payload["temperature"] = *options_.temperature;')
    patch('src/api.cpp','        opts.tool_discovery_threshold = options_.tool_discovery_threshold;','        opts.tool_discovery_threshold = options_.tool_discovery_threshold;\n        opts.temperature = options_.temperature;')
    patch('src/api.cpp','        if (!tools.descriptions.empty())\n            body["tools"] = tools.definitions(protocol);','        if (options_.temperature) {\n            if (protocol == ApiProtocol::Ollama) body["options"]["temperature"] = *options_.temperature;\n            else body["temperature"] = *options_.temperature;\n        }\n        if (!tools.descriptions.empty())\n            body["tools"] = tools.definitions(protocol);')
    receipt={'stamp':stamp,'extensions':['temperature-api-compatibility'],'compiledFiles':{name:hashlib.sha256((destination/name).read_bytes()).hexdigest() for name in sorted(set(changed))}}
    marker.write_text(json.dumps(receipt,indent=2)+'\n','utf-8')
    return destination,receipt
