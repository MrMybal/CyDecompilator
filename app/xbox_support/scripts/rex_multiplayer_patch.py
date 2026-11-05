"""Project-local multi-profile overlay and import routing; pinned SDK untouched."""
from pathlib import Path
import re
import json
import hashlib

MODULE = Path(__file__).resolve().parents[1]
SDK_SOURCE = MODULE / 'third_party/rexglue'


def prepare(project):
    project=Path(project).resolve()
    pinned=json.loads((SDK_SOURCE/'source.json').read_text('utf-8'))
    for relative,expected in pinned['files'].items():
        if hashlib.sha256((SDK_SOURCE/relative).read_bytes()).hexdigest()!=expected:
            raise ValueError('Packaged SDK profile source changed: '+relative)
    output=project/'native-overlay/multiplayer'
    output.mkdir(parents=True,exist_ok=True)
    header=(SDK_SOURCE/'include/rex/system/xam/user_profile.h').read_text(encoding='utf-8')
    header=header.replace('UserProfile','XboxNativeUserProfile')
    # Reuse the SDK's wire structures; only the profile implementation is local.
    start=header.index('struct X_USER_PROFILE_SETTING_DATA')
    end=header.index('class XboxNativeUserProfile')
    header=header[:start]+header[end:]
    header='#include <rex/system/xam/user_profile.h>\n'+header
    header=header.replace('  void set_kernel_state(KernelState* ks)',
        '  void SetLocalIdentity(uint64_t id, std::string name, std::filesystem::path directory) { xuid_=id; name_=std::move(name); directory_=std::move(directory); }\n  void set_kernel_state(KernelState* ks)')
    header=header.replace('  uint64_t xuid_;','  std::filesystem::path directory_;\n  uint64_t xuid_;')
    header='#include <filesystem>\n'+header
    (output/'rex_native_profile.h').write_text(header,encoding='utf-8',newline='\n')
    implementation=(SDK_SOURCE/'src/system/xam/user_profile.cpp').read_text(encoding='utf-8')
    implementation=implementation.replace('#include <rex/system/xam/user_profile.h>','#include "rex_native_profile.h"')
    implementation=implementation.replace('UserProfile','XboxNativeUserProfile')
    implementation=implementation.replace('kernel_state_->content_manager()->ResolveGameUserContentPath()',
        '(directory_.empty() ? kernel_state_->content_manager()->ResolveGameUserContentPath() : directory_ / fmt::format("{:08X}",kernel_state_->title_id()))')
    (output/'rex_native_profile.cpp').write_text(implementation,encoding='utf-8',newline='\n')
    user=(SDK_SOURCE/'src/kernel/xam/xam_user.cpp').read_text(encoding='utf-8')
    user=user[:user.index('// TODO(gibbed): probably a FILETIME/LARGE_INTEGER')]
    user=user.replace('REXCVAR_DEFINE_UINT32(user_language, 1, "Kernel", "User\'s language ID");','')
    user=user.replace('#include <rex/system/xam/user_profile.h>','#include "rex_native_profile.h"\n#include "rex_multiplayer.h"')
    user=user.replace('namespace xam {','namespace native_profiles {',1)
    user=user.replace('UserProfile','XboxNativeUserProfile')
    helper='''
XboxNativeUserProfile* NativeProfile(uint32_t index) {
  static std::recursive_mutex mutex;
  static std::unique_ptr<XboxNativeUserProfile> profiles[4];
  std::lock_guard lock(mutex);
  index=std::min(index,3u);
  if(!profiles[index]) {
    profiles[index]=std::make_unique<XboxNativeUserProfile>();
    profiles[index]->set_kernel_state(REX_KERNEL_STATE());
    const auto& original=REX_KERNEL_STATE()->user_profile();
    profiles[index]->SetLocalIdentity(XboxNativeUserId(index),
        index ? fmt::format("Joueur {}",index+1) : original->name(), XboxNativePlayerDirectory(index));
  }
  return profiles[index].get();
}
'''
    user=user.replace('i32 XamUserGetXUID_entry',helper+'\ni32 XamUserGetXUID_entry',1)
    user=user.replace('const auto& user_profile = REX_KERNEL_STATE()->user_profile();','auto* user_profile = NativeProfile(user_index);')
    user=user.replace('xam::XboxNativeUserProfile','rex::system::xam::XboxNativeUserProfile')
    user=user.replace('user_index == 0','user_index < XboxNativeLocalPlayers()')
    user=user.replace('if (user_index) {','if (user_index >= XboxNativeLocalPlayers()) {')
    user=user.replace('if (!xuids && user_index) {','if (!xuids && user_index >= XboxNativeLocalPlayers()) {')
    # Resolve a specific local XUID before the SDK's profile-settings path.
    user=user.replace('  if (!xuid_count) {','  if (xuid_count == 1 && xuids) {\n'
        '    for(unsigned i=0;i<XboxNativeLocalPlayers();++i) if(uint64_t(xuids[0])==XboxNativeUserId(i)) user_index=i;\n  }\n  if (!xuid_count) {',1)
    user=user.replace('BroadcastNotification(0x0000000A, 1)','BroadcastNotification(0x0000000A, (1u<<XboxNativeLocalPlayers())-1)')
    # Local profiles are offline. No synthetic membership or Live entitlement.
    user=user.replace('  return 1;\n}\n\nu32 XamUserGetMembershipTier_entry','  return 0;\n}\n\nu32 XamUserGetMembershipTier_entry')
    user=user.replace('  return 6 /* 6 appears to be Gold */;','  return 0;')
    user+='\n} } }\n'
    functions=re.findall(r'(?:i32|u32) (Xam\w+)_entry\(',user)
    for name in functions:
        user+=f'\nREX_EXPORT(__imp__XboxNative_{name}, rex::kernel::native_profiles::{name}_entry)\n'
    user='#include <mutex>\n'+user
    (output/'rex_native_users.cpp').write_text(user,encoding='utf-8',newline='\n')
    network=(MODULE/'native/rex_multiplayer.cpp').read_text(encoding='utf-8')
    raw_names=set(re.findall(r'REX_HOOK_RAW\(__imp__XboxNative_(\w+)\)',network))
    for name in sorted(raw_names):
        user+=f'\nextern "C" REX_FUNC(__imp__XboxNative_{name});\nstatic rex::ppc::detail::PPCFuncRegistrar native_reg_{name}("__imp__XboxNative_{name}", &__imp__XboxNative_{name});\n'
    (output/'rex_native_users.cpp').write_text(user,encoding='utf-8',newline='\n')
    names=set(functions)|raw_names
    manifest=next(project.glob('*_manifest.toml'))
    import tomllib
    config=tomllib.loads(manifest.read_text(encoding='utf-8'))
    generated=project/config['entrypoint']['out_directory_path']
    changed=[]
    imports=re.compile(r'\b__imp__('+'|'.join(re.escape(n) for n in sorted(names))+r')\b')
    for path in [*generated.glob('*.cpp'),*generated.glob('*.h')]:
        before=path.read_text(encoding='utf-8');after=before
        after=imports.sub(lambda match:'__imp__XboxNative_'+match[1],after)
        if after!=before:
            path.write_text(after,encoding='utf-8',newline='\n');changed.append(path.name)
    name=config['project']['name'];cmake=project/'CMakeLists.txt';text=cmake.read_text(encoding='utf-8')
    marker='# xbox-native multiplayer overlay'
    if marker not in text:
        text+=f'\n{marker}\ntarget_include_directories({name} PRIVATE "{output.as_posix()}" "{(MODULE/"native").as_posix()}")\n'
        text+=f'target_sources({name} PRIVATE "{(MODULE/"native/rex_multiplayer.cpp").as_posix()}" "{(output/"rex_native_profile.cpp").as_posix()}" "{(output/"rex_native_users.cpp").as_posix()}")\n'
        text+=f'target_link_libraries({name} PRIVATE ws2_32 bcrypt)\n'
        text+=f'target_compile_definitions({name} PRIVATE XBOX_NATIVE_MULTIPLAYER=1)\n'
        cmake.write_text(text,encoding='utf-8',newline='\n')
    checks_marker='# xbox-native multiplayer check linkage'
    if checks_marker not in text:
        text+=f'\n{checks_marker}\nif(TARGET native_controls_checks)\n'
        text+=f'  target_include_directories(native_controls_checks PRIVATE "{output.as_posix()}")\n'
        text+=f'  target_sources(native_controls_checks PRIVATE "{(MODULE/"native/rex_multiplayer.cpp").as_posix()}" "{(output/"rex_native_profile.cpp").as_posix()}" "{(output/"rex_native_users.cpp").as_posix()}")\n'
        text+='  target_link_libraries(native_controls_checks PRIVATE ws2_32 bcrypt)\nendif()\n'
        cmake.write_text(text,encoding='utf-8',newline='\n')
    record=dict(imports=sorted(names),files_changed=changed,original_user_source_sha256=hashlib.sha256((SDK_SOURCE/'src/kernel/xam/xam_user.cpp').read_bytes()).hexdigest())
    (project/'multiplayer-imports.json').write_text(json.dumps(record,indent=2)+'\n',encoding='utf-8')
    return record
