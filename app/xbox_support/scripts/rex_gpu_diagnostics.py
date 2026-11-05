"""Build an isolated diagnostic GPU plugin against the pinned ReXGlue runtime.

The official source checkout and the installed SDK remain unchanged.
"""
from pathlib import Path
import argparse
import hashlib
import json
import subprocess

from rex_project import MODULE, execute
from setup_backend import toolchain
from build_smaa import build as build_smaa
from build_rt import build as build_rt

COMMIT = 'f5337cdc947ff6d4c4196737e2c807a48f2a1fc2'


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise ValueError('Pinned source context changed: ' + old[:90])
    return text.replace(old, new)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work',type=Path)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--sdk', type=Path, required=True)
    parser.add_argument('--fix-occlusion', action='store_true')
    args = parser.parse_args()
    source, sdk = args.source.resolve(strict=True), args.sdk.resolve(strict=True)
    commit = subprocess.check_output(['git', '-c', 'safe.directory=' + source.as_posix(),
                                     '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
    if commit != COMMIT:
        raise ValueError('Requires the pinned ReXGlue source commit')
    work = args.work or MODULE.parents[1]/'runtime/engines/xbox-native-gpu'/COMMIT[:12]
    work.mkdir(parents=True, exist_ok=True)
    build_smaa(work)
    build_rt(work)
    original = source / 'src/graphics/d3d12/command_processor.cpp'
    contents = original.read_text(encoding='utf-8')
    contents = ('#include <rex/cvar.h>\n'
        'REXCVAR_DEFINE_INT32(native_querybatch_range, 0, "GPU", '
        '"Opt-in bounded QueryBatch compatibility counters; 0 uses host queries");\n' + contents)
    if args.fix_occlusion:
        from rex_occlusion_patch import patch as patch_occlusion
        command_header = (source / 'include/rex/graphics/d3d12/command_processor.h').read_text(encoding='utf-8')
        contents, command_header = patch_occlusion(contents, command_header, MODULE, replace_once)
        command_header_path = work / 'include/rex/graphics/d3d12/command_processor.h'
        command_header_path.parent.mkdir(parents=True, exist_ok=True)
        command_header_path.write_text(command_header, encoding='utf-8', newline='\n')
        contents = replace_once(contents, '  samples = NormalizeOcclusionSamples(samples);',
            '  samples = NormalizeOcclusionSamples(samples);\n'
            '  static uint64_t query_number = 0;\n'
            '  if (++query_number <= 16 || query_number % 1000 == 0)\n'
            '    REXGPU_INFO("[xbox-native] Occlusion readback #{}: addr={:08X}, samples={}, segments={}", query_number, sample_count_address, samples, segments.size());')
    resources = (MODULE / 'native/rex_smaa_resources.h').as_posix()
    dispatch = (MODULE / 'native/rex_smaa_dispatch.inl').as_posix()
    # Include after SDK declarations and util headers have been made available.
    contents = replace_once(contents, 'namespace rex::graphics::d3d12 {',
        f'#include "{resources}"\n#include "{(MODULE / "native/rex_rt_gpu.h").as_posix()}"\n\nnamespace rex::graphics::d3d12 {{')
    contents = replace_once(contents,
        '  AwaitAllQueueOperationsCompletion();\n  InvalidateAllVertexBufferResidency();',
        '  AwaitAllQueueOperationsCompletion();\n  NativeRtShutdown();\n  native_smaa.reset();\n  InvalidateAllVertexBufferResidency();')
    contents = replace_once(contents,
        'ui::d3d12::util::CreateRootSignature(GetD3D12Provider(), desc);',
        'NativeRtCreateRoot(GetD3D12Provider(), desc);')
    # Both bindless graphics signatures receive a spare GS-only constant block.
    contents = contents.replace('ui::d3d12::util::CreateRootSignature(provider, root_signature_bindless_desc);',
                                 'NativeRtCreateRoot(provider, root_signature_bindless_desc);')
    capture = '''
    if (NativeRtEnabled() && !memexport_used && host_render_targets_used &&
        normalized_depth_control.z_enable && pixel_shader &&
        (normalized_color_mask & 15)) {
      NativeRtDraw capture{};
      capture.device = GetD3D12Provider().GetDevice();
      capture.pipeline = pipeline_cache_->GetD3D12PipelineByHandle(pipeline_handle);
      capture.root = root_signature;
      capture.count = primitive_processing_result.host_draw_vertex_count;
      capture.indexed = NATIVE_INDEXED;
      capture.triangles = primitive_topology_ == D3D_PRIMITIVE_TOPOLOGY_TRIANGLELIST
          ? capture.count / 3 : (primitive_topology_ == D3D_PRIMITIVE_TOPOLOGY_TRIANGLESTRIP && capture.count > 2 ? capture.count - 2 : 0);
      capture.viewport = ff_viewport_;
      capture.scissor = ff_scissor_;
      auto native_colour_control=regs.Get<reg::RB_COLORCONTROL>();
      capture.material_flags=(native_colour_control.alpha_test_enable || native_colour_control.alpha_to_mask_enable) ? 16u : 0u;
      std::memcpy(capture.scale, system_constants_.ndc_scale, sizeof(capture.scale));
      std::memcpy(capture.offset, system_constants_.ndc_offset, sizeof(capture.offset));
      // Exclude extra material/depth passes from guest visibility counters.
      bool resume_query = active_occlusion_query_.valid;
      if (resume_query && active_occlusion_query_.host_index != UINT32_MAX) {
        auto index = active_occlusion_query_.host_index;
        deferred_command_list_.D3DEndQuery(occlusion_query_heap_.Get(), D3D12_QUERY_TYPE_OCCLUSION, index);
        deferred_command_list_.D3DResolveQueryData(occlusion_query_heap_.Get(), D3D12_QUERY_TYPE_OCCLUSION,
            index, 1, occlusion_query_readback_.Get(), sizeof(uint64_t) * index);
        active_occlusion_query_.segments.push_back(index);
        active_occlusion_query_.host_index = UINT32_MAX;
      }
      deferred_command_list_.NativeCallback(NativeRtCapture, sizeof(capture), &capture);
      if (resume_query) {
        uint32_t index;
        if (!AcquireOcclusionQueryIndex(index)) return false;
        active_occlusion_query_.host_index = index;
        deferred_command_list_.D3DBeginQuery(occlusion_query_heap_.Get(), D3D12_QUERY_TYPE_OCCLUSION, index);
      }
    }
'''
    contents = replace_once(contents,
        '    deferred_command_list_.D3DDrawInstanced(primitive_processing_result.host_draw_vertex_count, 1,\n                                            0, 0);',
        '    deferred_command_list_.D3DDrawInstanced(primitive_processing_result.host_draw_vertex_count, 1,\n                                            0, 0);' + capture.replace('NATIVE_INDEXED', '0'))
    contents = replace_once(contents,
        '    deferred_command_list_.D3DDrawIndexedInstanced(\n        primitive_processing_result.host_draw_vertex_count, 1, 0, 0, 0);',
        '    deferred_command_list_.D3DDrawIndexedInstanced(\n        primitive_processing_result.host_draw_vertex_count, 1, 0, 0, 0);' + capture.replace('NATIVE_INDEXED', '1'))
    contents = replace_once(contents,
        '        SubmitBarriers();\n        EndSubmission(true);',
        '        SubmitBarriers();\n'
        '        NativeRtPresent rt_present{guest_output_resource, ui::d3d12::D3D12Presenter::kGuestOutputInternalState};\n'
        '        deferred_command_list_.NativeCallback(NativeRtComposite, sizeof(rt_present), &rt_present);\n'
        '        EndSubmission(true);')
    contents = replace_once(contents,
        '        bool use_fxaa = swap_post_effect == SwapPostEffect::kFxaa ||\n                        swap_post_effect == SwapPostEffect::kFxaaExtreme;',
        '        bool use_fxaa = swap_post_effect != SwapPostEffect::kNone;')
    contents = replace_once(contents, 'fxaa_descriptors[2];', 'fxaa_descriptors[8];')
    contents = replace_once(contents,
        '            SetExternalPipeline(swap_post_effect == SwapPostEffect::kFxaaExtreme\n'
        '                                    ? fxaa_extreme_pipeline_.Get()\n'
        '                                    : fxaa_pipeline_.Get());\n'
        '            SubmitBarriers();\n'
        '            deferred_command_list_.D3DDispatch(group_count_x, group_count_y, 1);',
        f'            #include "{dispatch}"')
    (work / 'command_processor.cpp').write_text(contents, encoding='utf-8', newline='\n')
    # Local deferred-stream extension: callbacks execute at the exact recorded
    # GPU-list position, so capture sees the original draw's shader resources.
    header = (source / 'include/rex/graphics/d3d12/deferred_command_list.h').read_text(encoding='utf-8')
    header = replace_once(header, '  void Reset();', '''  void NativeCallback(void (*callback)(ID3D12GraphicsCommandList *, const void *), uint32_t size, const void *payload) {
    auto *args = static_cast<NativeCallbackHeader *>(WriteCommand(Command::kNativeCallback, sizeof(NativeCallbackHeader) + size));
    args->callback = callback;
    std::memcpy(args + 1, payload, size);
  }
  void Reset();''')
    header = replace_once(header, '  enum class Command {', '  struct NativeCallbackHeader { void (*callback)(ID3D12GraphicsCommandList *, const void *); };\n  enum class Command {\n    kNativeCallback,')
    local_header = work / 'include/rex/graphics/d3d12/deferred_command_list.h'
    local_header.parent.mkdir(parents=True, exist_ok=True)
    local_header.write_text(header, encoding='utf-8', newline='\n')
    deferred = (source / 'src/graphics/d3d12/deferred_command_list.cpp').read_text(encoding='utf-8')
    deferred = f'#include "{(MODULE / "native/rex_rt_gpu.h").as_posix()}"\n' + deferred
    deferred = replace_once(deferred,
        '        command_list->OMSetRenderTargets(\n',
        '        NativeRtRememberTargets(args.num_render_target_descriptors, args.render_target_descriptors,\n'
        '            args.rts_single_handle_to_descriptor_range ? TRUE : FALSE,\n'
        '            args.depth_stencil ? &args.depth_stencil_descriptor : nullptr);\n'
        '        command_list->OMSetRenderTargets(\n')
    deferred = replace_once(deferred, '    switch (header.command) {',
        '    switch (header.command) {\n'
        '      case Command::kNativeCallback: {\n'
        '        auto &args = *reinterpret_cast<const NativeCallbackHeader *>(stream);\n'
        '        args.callback(command_list, &args + 1);\n'
        '      } break;')
    (work / 'deferred_command_list.cpp').write_text(deferred, encoding='utf-8', newline='\n')
    pipeline = (source / 'src/graphics/d3d12/pipeline_cache.cpp').read_text(encoding='utf-8')
    pipeline = f'#include "{(MODULE / "native/rex_rt_gpu.h").as_posix()}"\n' + pipeline
    pipeline = replace_once(pipeline, '  std::u16string name;',
        '  NativeRtRegisterPipeline(device, state_desc, state);\n  std::u16string name;')
    (work / 'pipeline_cache.cpp').write_text(pipeline, encoding='utf-8', newline='\n')
    core = (source / 'src/graphics/command_processor.cpp').read_text(encoding='utf-8')
    core = ('#include <atomic>\n#include <cstdint>\n#include <rex/system/gpu_plugin.h>\n'
            'namespace { std::atomic<uint64_t> native_guest_frames{0}; std::atomic<int> native_aa{3}; }\n' + core)
    core += '\nextern "C" REX_GPU_PLUGIN_EXPORT uint64_t rex_gpu_guest_frame_count() { return native_guest_frames.load(std::memory_order_relaxed); }\n'
    core += ('extern "C" REX_GPU_PLUGIN_EXPORT void rex_gpu_set_antialiasing(int mode) { '
             'if (mode >= 0 && mode <= 3) native_aa.store(mode, std::memory_order_relaxed); }\n')
    # Already on the GPU thread: switch only the render-side effect, without
    # changing the game's MSAA state, render targets or simulation settings.
    core = replace_once(core,
        '  IssueSwap(frontbuffer_ptr, frontbuffer_width, frontbuffer_height);',
        '  const int aa = native_aa.load(std::memory_order_relaxed);\n'
        '  swap_post_effect_actual_ = static_cast<SwapPostEffect>(aa);\n'
        '  IssueSwap(frontbuffer_ptr, frontbuffer_width, frontbuffer_height);')
    core = replace_once(core, '  ++counter_;\n  return true;',
                        '  native_guest_frames.fetch_add(1, std::memory_order_relaxed);\n  ++counter_;\n  return true;')
    (work / 'core_command_processor.cpp').write_text(core, encoding='utf-8', newline='\n')
    cmake_text = (source / 'src/graphics/CMakeLists.txt').read_text(encoding='utf-8')
    cmake_text = cmake_text.replace('add_library(rex::gpu-xenos ALIAS rexgpu-xenos)', '')
    cmake_text = cmake_text.replace('    rexruntime\n', '    rex::runtime\n')
    cmake_text = cmake_text.replace('    xxHash::xxhash\n', '    rex::xxhash\n')
    cmake_text = replace_once(cmake_text,
        'add_library(rexgpu-xenos SHARED ${REXGPU_XENOS_SOURCES})',
        'set(ABSOLUTE_SOURCES)\nforeach(file IN LISTS REXGPU_XENOS_SOURCES)\n'
        '  if(file STREQUAL "d3d12/command_processor.cpp")\n'
        '    list(APPEND ABSOLUTE_SOURCES "${CMAKE_CURRENT_SOURCE_DIR}/command_processor.cpp")\n'
        '  elseif(file STREQUAL "command_processor.cpp")\n'
        '    list(APPEND ABSOLUTE_SOURCES "${CMAKE_CURRENT_SOURCE_DIR}/core_command_processor.cpp")\n'
        '  elseif(file STREQUAL "d3d12/deferred_command_list.cpp" OR file STREQUAL "d3d12/pipeline_cache.cpp")\n'
        '    get_filename_component(LOCAL_NAME "${file}" NAME)\n'
        '    list(APPEND ABSOLUTE_SOURCES "${CMAKE_CURRENT_SOURCE_DIR}/${LOCAL_NAME}")\n'
        '  elseif(IS_ABSOLUTE "${file}")\n    list(APPEND ABSOLUTE_SOURCES "${file}")\n'
        '  else()\n    list(APPEND ABSOLUTE_SOURCES "${REXGLUE_ROOT}/src/graphics/${file}")\n'
        '  endif()\nendforeach()\nadd_library(rexgpu-xenos SHARED ${ABSOLUTE_SOURCES})\n'
        'set_target_properties(rexgpu-xenos PROPERTIES OUTPUT_NAME "rexgpu-xenos-' + ('occlusion' if args.fix_occlusion else 'local') + '")')
    prefix = (f'cmake_minimum_required(VERSION 3.25)\nproject(XboxNativeGpu LANGUAGES CXX)\n'
              f'set(CMAKE_CXX_STANDARD 23)\nset(CMAKE_CXX_STANDARD_REQUIRED ON)\n'
              f'find_package(rexglue CONFIG REQUIRED)\nset(REXGLUE_USE_D3D12 ON)\n'
              f'set(REXGLUE_ROOT "{source.as_posix()}")\n'
              f'include("{source.as_posix()}/cmake/rex_pch.cmake")\n'
              f'include_directories("{source.as_posix()}/src/graphics/d3d12")\n'
              f'include_directories("{work.as_posix()}/smaa" "{MODULE.as_posix()}/third_party/smaa/Textures")\n'
              f'include_directories(BEFORE "{work.as_posix()}/include" "{work.as_posix()}/rt")\n'
              f'add_compile_options(-msse4.1 -fno-strict-aliasing -ffp-model=strict -fno-char8_t)\n')
    cmake_text += f'\ntarget_sources(rexgpu-xenos PRIVATE "{(MODULE / "native/rex_rt_gpu.cpp").as_posix()}")\n'
    cmake_text += '\ntarget_link_libraries(rexgpu-xenos PRIVATE d3dcompiler)\n'
    cmake_text += (f'\nadd_executable(native_rt_checks EXCLUDE_FROM_ALL "{(MODULE / "native/rex_rt_smoke.cpp").as_posix()}")\n'
                   'target_link_libraries(native_rt_checks PRIVATE rex::runtime d3d12 dxgi d3dcompiler)\n')
    (work / 'CMakeLists.txt').write_text(prefix + cmake_text, encoding='utf-8', newline='\n')
    cmake, env, options = toolchain()
    options = [x.replace('clang-cl.exe', 'clang.exe') if x.startswith('-DCMAKE_C_COMPILER=')
               else x.replace('clang-cl.exe', 'clang++.exe') if x.startswith('-DCMAKE_CXX_COMPILER=')
               else x for x in options]
    execute([cmake, '-S', work, '-B', work / 'build', *options,
             '-DCMAKE_PREFIX_PATH=' + str(sdk), '-DCMAKE_BUILD_TYPE=Release'], work, 'configure', env)
    execute([cmake, '--build', work / 'build', '--parallel', '4'], work, 'build', env)
    plugin = work / ('build/rexgpu-xenos-occlusion.dll' if args.fix_occlusion else 'build/rexgpu-xenos-local.dll')
    receipt = dict(source_commit=commit, occlusion_pair_fix=args.fix_occlusion,
                   original_source_sha256=hashlib.sha256(original.read_bytes()).hexdigest(),
                   occlusion_orphan_recovery=args.fix_occlusion,
                   occlusion_segment_accumulation=args.fix_occlusion,
                   occlusion_cumulative_snapshots=args.fix_occlusion,
                   querybatch_compatibility_range='opt_in_0_to_65536',
                   plugin=str(plugin), sha256=hashlib.sha256(plugin.read_bytes()).hexdigest(),
                   native_antialiasing=['none', 'fxaa', 'fxaa_extreme', 'smaa_1x_high'],
                   native_raytracing=['dxr_ambient_occlusion', 'experimental_reflections', 'material_radiance_diffuse_bounce'],
                   materials=dict(source='original_pixel_shader_replay', tile_size=16,
                                  triangle_capacity=131072, alpha_test='original_shader_discard',
                                  transparency='stochastic_alpha', emissive='shaded_HDR_radiance_not_separate_emission_channel'),
                   denoising='two_pass_depth_normal_guided_spatial_bilateral',
                   primary_visibility='original_shader_raster_depth_replay_2048',
                   scene_selection='single_perspective_viewport_and_depth_target',
                   capture_signatures=list(range(17)),
                   geometry_source='post_vertex_shader_triangle_capture',
                   smaa_source=json.loads((MODULE / 'third_party/smaa/source.json').read_text()),
                   smaa_shaders={path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                                 for path in (work / 'smaa').glob('smaa_*.h')})
    (work / 'plugin.json').write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    main()
