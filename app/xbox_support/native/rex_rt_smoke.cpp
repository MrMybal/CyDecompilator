// One bounded, windowless GPU check of the actual capture -> BLAS/TLAS -> AO
// path.
#include "rex_occlusion_packet_checks.inl"
#include "rex_rt_gpu.cpp"
#include <bit>
#include <cstdio>
#include <d3dcompiler.h>
#include <stdexcept>

void require(HRESULT hr) {
  if (FAILED(hr))
    throw std::runtime_error("D3D12 call failed: " +
                             std::to_string(uint32_t(hr)));
}
int main() {
  try {
    occlusion_packet_check::Run();
    ComPtr<ID3D12Device> device;
    require(D3D12CreateDevice(nullptr, D3D_FEATURE_LEVEL_12_1,
                              IID_PPV_ARGS(&device)));
    ComPtr<ID3D12CommandQueue> queue;
    D3D12_COMMAND_QUEUE_DESC q{};
    q.Type = D3D12_COMMAND_LIST_TYPE_DIRECT;
    require(device->CreateCommandQueue(&q, IID_PPV_ARGS(&queue)));
    ComPtr<ID3D12CommandAllocator> allocator;
    require(device->CreateCommandAllocator(q.Type, IID_PPV_ARGS(&allocator)));
    ComPtr<ID3D12GraphicsCommandList> list;
    require(device->CreateCommandList(0, q.Type, allocator.Get(), nullptr,
                                      IID_PPV_ARGS(&list)));
    D3D12_ROOT_PARAMETER param{};
    param.ParameterType = D3D12_ROOT_PARAMETER_TYPE_32BIT_CONSTANTS;
    param.Constants = {15, 15, 8};
    param.ShaderVisibility = D3D12_SHADER_VISIBILITY_GEOMETRY;
    D3D12_DESCRIPTOR_RANGE material_range_desc{D3D12_DESCRIPTOR_RANGE_TYPE_SRV,
                                               1, 0, 0, 0};
    D3D12_ROOT_PARAMETER root_params[2]{param, {}};
    root_params[1].ParameterType = D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE;
    root_params[1].DescriptorTable = {1, &material_range_desc};
    root_params[1].ShaderVisibility = D3D12_SHADER_VISIBILITY_PIXEL;
    D3D12_ROOT_SIGNATURE_DESC root_desc{
        2, root_params, 0, nullptr,
        D3D12_ROOT_SIGNATURE_FLAG_ALLOW_STREAM_OUTPUT};
    ComPtr<ID3DBlob> blob, errors;
    require(D3D12SerializeRootSignature(
        &root_desc, D3D_ROOT_SIGNATURE_VERSION_1, &blob, &errors));
    ComPtr<ID3D12RootSignature> root;
    require(device->CreateRootSignature(0, blob->GetBufferPointer(),
                                        blob->GetBufferSize(),
                                        IID_PPV_ARGS(&root)));
    root_parameters[root.Get()] = 0;
    const char *source = R"(
      struct Vertex { float4 tex[16]:TEXCOORD0; float4 position:SV_Position; };
      Vertex main(uint id:SV_VertexID) {
        const float3 v[12] = {
          float3(-4,-4,4),float3(4,-4,4),float3(-4,4,4),
          float3(-4,4,4),float3(4,-4,4),float3(4,4,4),
          float3(.1,-2,3),float3(2,-2,3),float3(.1,2,3),
          float3(.1,2,3),float3(2,-2,3),float3(2,2,3)};
        Vertex output;
        [unroll] for (uint i=0; i<16; ++i) output.tex[i] = float4(v[id].x*.25+.5, v[id].y*.25+.5, id>=6 ? 1 : 0, i);
        output.position = float4(v[id].xy, v[id].z - .1, v[id].z);
        return output;
      })";
    ComPtr<ID3DBlob> vs;
    require(D3DCompile(source, std::strlen(source), nullptr, nullptr, nullptr,
                       "main", "vs_5_1", D3DCOMPILE_OPTIMIZATION_LEVEL3, 0, &vs,
                       &errors));
    const char *pixel_source = R"(
      Texture2D<float4> material_texture:register(t0);
      struct Vertex { float4 tex[16]:TEXCOORD0; float4 position:SV_Position; };
      float4 main(Vertex input):SV_Target0 {
        // Texture-driven cutout coverage, plus HDR/emissive radiance and alpha=0
        // on opaque surfaces. None of those may become a solid black blocker.
        float alpha=material_texture.Load(int3(uint2(saturate(input.tex[0].xy)*3),0)).a;
        if(input.tex[0].z>.5) clip(alpha-.5);
        return float4(input.tex[0].x>0.85 ? 3 : .3,.3,.3,0);
      })";
    ComPtr<ID3DBlob> ps;
    require(D3DCompile(pixel_source, std::strlen(pixel_source), nullptr,
                       nullptr, nullptr, "main", "ps_5_1",
                       D3DCOMPILE_OPTIMIZATION_LEVEL3, 0, &ps, &errors));
    D3D12_GRAPHICS_PIPELINE_STATE_DESC desc{};
    desc.pRootSignature = root.Get();
    desc.VS = {vs->GetBufferPointer(), vs->GetBufferSize()};
    desc.PS = {ps->GetBufferPointer(), ps->GetBufferSize()};
    desc.NumRenderTargets = 1;
    desc.RTVFormats[0] = DXGI_FORMAT_R8G8B8A8_UNORM;
    desc.PrimitiveTopologyType = D3D12_PRIMITIVE_TOPOLOGY_TYPE_TRIANGLE;
    desc.SampleDesc.Count = 1;
    desc.SampleMask = UINT_MAX;
    desc.RasterizerState.FillMode = D3D12_FILL_MODE_SOLID;
    desc.RasterizerState.CullMode = D3D12_CULL_MODE_NONE;
    desc.RasterizerState.DepthClipEnable = TRUE;
    desc.DepthStencilState.DepthFunc = D3D12_COMPARISON_FUNC_ALWAYS;
    for (auto &blend : desc.BlendState.RenderTarget) {
      blend.SrcBlend = blend.SrcBlendAlpha = D3D12_BLEND_ONE;
      blend.DestBlend = blend.DestBlendAlpha = D3D12_BLEND_ZERO;
      blend.BlendOp = blend.BlendOpAlpha = D3D12_BLEND_OP_ADD;
      blend.LogicOp = D3D12_LOGIC_OP_NOOP;
      blend.RenderTargetWriteMask = 15;
    }
    ComPtr<ID3D12PipelineState> original;
    require(
        device->CreateGraphicsPipelineState(&desc, IID_PPV_ARGS(&original)));
    NativeRtRegisterPipeline(device.Get(), desc, original.Get());
    auto capture_layout = pipelines.at(original.Get());
    auto legacy_desc = capture_layout->desc;
    legacy_desc.GS = {native_rt_capture, sizeof(native_rt_capture)};
    D3D12_SO_DECLARATION_ENTRY legacy_entry{0, "TEXCOORD", 16, 0, 4, 0};
    UINT legacy_stride = 16;
    legacy_desc.StreamOutput = {&legacy_entry, 1, &legacy_stride, 1,
                                D3D12_SO_NO_RASTERIZED_STREAM};
    ComPtr<ID3D12PipelineState> legacy;
    bool legacy_rejected = FAILED(device->CreateGraphicsPipelineState(
        &legacy_desc, IID_PPV_ARGS(&legacy)));
    ComPtr<ID3D12Resource> output;
    D3D12_HEAP_PROPERTIES heap{};
    heap.Type = D3D12_HEAP_TYPE_DEFAULT;
    D3D12_RESOURCE_DESC td{};
    td.Dimension = D3D12_RESOURCE_DIMENSION_TEXTURE2D;
    td.Width = td.Height = 64;
    td.DepthOrArraySize = td.MipLevels = td.SampleDesc.Count = 1;
    td.Format = DXGI_FORMAT_R8G8B8A8_UNORM;
    td.Flags = D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS |
               D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET;
    require(device->CreateCommittedResource(&heap, D3D12_HEAP_FLAG_NONE, &td,
                                            D3D12_RESOURCE_STATE_RENDER_TARGET,
                                            nullptr, IID_PPV_ARGS(&output)));
    D3D12_DESCRIPTOR_HEAP_DESC hd{D3D12_DESCRIPTOR_HEAP_TYPE_RTV, 1,
                                  D3D12_DESCRIPTOR_HEAP_FLAG_NONE, 0};
    ComPtr<ID3D12DescriptorHeap> rtv;
    require(device->CreateDescriptorHeap(&hd, IID_PPV_ARGS(&rtv)));
    device->CreateRenderTargetView(output.Get(), nullptr,
                                   rtv->GetCPUDescriptorHandleForHeapStart());
    auto target = rtv->GetCPUDescriptorHandleForHeapStart();
    NativeRtRememberTargets(1, &target, FALSE, nullptr);
    list->OMSetRenderTargets(1, &target, FALSE, nullptr);
    // Retain the original draw's material descriptor heap across capture.
    ComPtr<ID3D12Resource> texture, texture_upload;
    auto texture_desc = td;
    texture_desc.Width = texture_desc.Height = 4;
    texture_desc.Flags = D3D12_RESOURCE_FLAG_NONE;
    require(device->CreateCommittedResource(
        &heap, D3D12_HEAP_FLAG_NONE, &texture_desc,
        D3D12_RESOURCE_STATE_COPY_DEST, nullptr, IID_PPV_ARGS(&texture)));
    if (!buffer(device.Get(), texture_upload, 1024, D3D12_HEAP_TYPE_UPLOAD,
                D3D12_RESOURCE_STATE_GENERIC_READ))
      throw std::runtime_error("Texture upload allocation failed");
    void *texels = nullptr;
    D3D12_RANGE no_read{};
    require(texture_upload->Map(0, &no_read, &texels));
    std::memset(texels, 0, 1024);
    for (unsigned y = 0; y < 4; ++y)
      for (unsigned x = 0; x < 4; ++x) {
        auto *pixel = static_cast<uint8_t *>(texels) + y * 256 + x * 4;
        pixel[0] = pixel[1] = pixel[2] = 255;
        pixel[3] = x >= 2 ? 255 : 0;
      }
    texture_upload->Unmap(0, nullptr);
    D3D12_TEXTURE_COPY_LOCATION texture_src{}, texture_dst{};
    texture_src.pResource = texture_upload.Get();
    texture_src.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;
    texture_src.PlacedFootprint.Footprint = {td.Format, 4, 4, 1, 256};
    texture_dst.pResource = texture.Get();
    texture_dst.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
    list->CopyTextureRegion(&texture_dst, 0, 0, 0, &texture_src, nullptr);
    transition(list.Get(), texture.Get(), D3D12_RESOURCE_STATE_COPY_DEST,
               D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE);
    ComPtr<ID3D12DescriptorHeap> texture_heap;
    D3D12_DESCRIPTOR_HEAP_DESC th{D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV, 1,
                                  D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE, 0};
    require(device->CreateDescriptorHeap(&th, IID_PPV_ARGS(&texture_heap)));
    D3D12_SHADER_RESOURCE_VIEW_DESC tv{};
    tv.Format = td.Format;
    tv.ViewDimension = D3D12_SRV_DIMENSION_TEXTURE2D;
    tv.Texture2D.MipLevels = 1;
    tv.Shader4ComponentMapping = D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;
    device->CreateShaderResourceView(
        texture.Get(), &tv, texture_heap->GetCPUDescriptorHandleForHeapStart());
    auto *material_heap = texture_heap.Get();
    list->SetDescriptorHeaps(1, &material_heap);
    float white[4] = {.4f, .4f, .4f, 1};
    list->ClearRenderTargetView(rtv->GetCPUDescriptorHandleForHeapStart(),
                                white, 0, nullptr);
    list->SetGraphicsRootSignature(root.Get());
    list->SetGraphicsRootDescriptorTable(
        1, texture_heap->GetGPUDescriptorHandleForHeapStart());
    list->SetPipelineState(original.Get());
    list->IASetPrimitiveTopology(D3D_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
    rex_gpu_set_raytracing(1, .75f, 2.f);
    rex_gpu_set_rt_projection(1.57079632679f, 1.f);
    NativeRtDraw draw{device.Get(), original.Get(), root.Get(), 12, 0,
                      {1, 1, 1},    {0, 0, 0}};
    draw.triangles = 4;
    draw.viewport = {0, 0, 64, 64, 0, 1};
    draw.scissor = {0, 0, 64, 64};
    NativeRtCapture(list.Get(), &draw);
    NativeRtPresent present{output.Get(), D3D12_RESOURCE_STATE_RENDER_TARGET};
    NativeRtComposite(list.Get(), &present);
    if (status.load() != 2)
      throw std::runtime_error(
          "Native DXR path did not initialize/capture/dispatch");
    transition(list.Get(), output.Get(), present.state,
               D3D12_RESOURCE_STATE_COPY_SOURCE);
    ComPtr<ID3D12Resource> readback;
    if (!buffer(device.Get(), readback, 64 * 256, D3D12_HEAP_TYPE_READBACK,
                D3D12_RESOURCE_STATE_COPY_DEST))
      throw std::runtime_error("Readback allocation failed");
    D3D12_TEXTURE_COPY_LOCATION dst{}, src{};
    dst.pResource = readback.Get();
    dst.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;
    dst.PlacedFootprint.Footprint = {td.Format, 64, 64, 1, 256};
    src.pResource = output.Get();
    src.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
    list->CopyTextureRegion(&dst, 0, 0, 0, &src, nullptr);
    ComPtr<ID3D12Resource> depth_readback, guide_readback;
    if (!buffer(device.Get(), depth_readback, 64 * 256,
                D3D12_HEAP_TYPE_READBACK, D3D12_RESOURCE_STATE_COPY_DEST) ||
        !buffer(device.Get(), guide_readback, 64 * 512,
                D3D12_HEAP_TYPE_READBACK, D3D12_RESOURCE_STATE_COPY_DEST))
      throw std::runtime_error("Guide readback allocation failed");
    D3D12_BOX debug_box{0, 0, 0, 64, 64, 1};
    D3D12_TEXTURE_COPY_LOCATION debug_dst{}, debug_src{};
    debug_dst.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;
    debug_src.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
    debug_dst.pResource = depth_readback.Get();
    debug_dst.PlacedFootprint.Footprint = {DXGI_FORMAT_R32_TYPELESS, 64, 64, 1,
                                           256};
    debug_src.pResource = rt->raster_depth.Get();
    transition(list.Get(), rt->raster_depth.Get(), rt->raster_depth_state,
               D3D12_RESOURCE_STATE_COPY_SOURCE);
    list->CopyTextureRegion(&debug_dst, 0, 0, 0, &debug_src, &debug_box);
    transition(list.Get(), rt->raster_depth.Get(),
               D3D12_RESOURCE_STATE_COPY_SOURCE, rt->raster_depth_state);
    debug_dst.pResource = guide_readback.Get();
    debug_dst.PlacedFootprint.Footprint = {DXGI_FORMAT_R16G16B16A16_FLOAT, 64,
                                           64, 1, 512};
    debug_src.pResource = rt->images.front()->guide.Get();
    transition(list.Get(), debug_src.pResource,
               D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,
               D3D12_RESOURCE_STATE_COPY_SOURCE);
    list->CopyTextureRegion(&debug_dst, 0, 0, 0, &debug_src, &debug_box);
    transition(list.Get(), debug_src.pResource,
               D3D12_RESOURCE_STATE_COPY_SOURCE,
               D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
    // Read the actual material-shader output, including alpha-discard holes.
    ComPtr<ID3D12Resource> material_readback;
    if (!buffer(device.Get(), material_readback, 512 * 16,
                D3D12_HEAP_TYPE_READBACK, D3D12_RESOURCE_STATE_COPY_DEST))
      throw std::runtime_error("Material readback allocation failed");
    transition(list.Get(), rt->materials.Get(), rt->material_state,
               D3D12_RESOURCE_STATE_COPY_SOURCE);
    D3D12_TEXTURE_COPY_LOCATION material_dst{}, material_src{};
    material_dst.pResource = material_readback.Get();
    material_dst.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;
    material_dst.PlacedFootprint.Footprint = {DXGI_FORMAT_R16G16B16A16_FLOAT,
                                              64, 16, 1, 512};
    material_src.pResource = rt->materials.Get();
    material_src.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
    D3D12_BOX box{0, 0, 0, 64, 16, 1};
    list->CopyTextureRegion(&material_dst, 0, 0, 0, &material_src, &box);
    rt->material_state = D3D12_RESOURCE_STATE_COPY_SOURCE;
    // The same alpha=0 shader under alpha blending must become transparent,
    // while it remained opaque above. Exercise the real candidate decisions.
    auto transparent_desc = desc;
    auto &transparent_blend = transparent_desc.BlendState.RenderTarget[0];
    transparent_blend.BlendEnable = TRUE;
    transparent_blend.SrcBlend = D3D12_BLEND_SRC_ALPHA;
    transparent_blend.DestBlend = D3D12_BLEND_INV_SRC_ALPHA;
    ComPtr<ID3D12PipelineState> transparent;
    require(device->CreateGraphicsPipelineState(&transparent_desc,
                                                IID_PPV_ARGS(&transparent)));
    NativeRtRegisterPipeline(device.Get(), transparent_desc, transparent.Get());
    transition(list.Get(), output.Get(), D3D12_RESOURCE_STATE_COPY_SOURCE,
               present.state);
    list->SetDescriptorHeaps(1, &material_heap);
    list->SetGraphicsRootDescriptorTable(
        1, texture_heap->GetGPUDescriptorHandleForHeapStart());
    draw.pipeline = transparent.Get();
    NativeRtCapture(list.Get(), &draw);
    NativeRtComposite(list.Get(), &present);
    transition(list.Get(), output.Get(), present.state,
               D3D12_RESOURCE_STATE_COPY_SOURCE);
    ComPtr<ID3D12Resource> transparent_readback;
    if (!buffer(device.Get(), transparent_readback, 64 * 256,
                D3D12_HEAP_TYPE_READBACK, D3D12_RESOURCE_STATE_COPY_DEST))
      throw std::runtime_error("Transparency readback allocation failed");
    dst.pResource = transparent_readback.Get();
    list->CopyTextureRegion(&dst, 0, 0, 0, &src, nullptr);
    require(list->Close());
    ID3D12CommandList *submit[] = {list.Get()};
    queue->ExecuteCommandLists(1, submit);
    ComPtr<ID3D12Fence> fence;
    require(
        device->CreateFence(0, D3D12_FENCE_FLAG_NONE, IID_PPV_ARGS(&fence)));
    HANDLE event = CreateEventW(nullptr, FALSE, FALSE, nullptr);
    require(queue->Signal(fence.Get(), 1));
    require(fence->SetEventOnCompletion(1, event));
    DWORD wait = WaitForSingleObject(event, 10000);
    CloseHandle(event);
    if (wait != WAIT_OBJECT_0)
      throw std::runtime_error("GPU check exceeded ten seconds");
    require(device->GetDeviceRemovedReason());
    void *debug_depth = nullptr, *debug_guide = nullptr;
    D3D12_RANGE debug_range{0, 64 * 256};
    require(depth_readback->Map(0, &debug_range, &debug_depth));
    D3D12_RANGE debug_guide_range{0, 64 * 512};
    require(guide_readback->Map(0, &debug_guide_range, &debug_guide));
    unsigned guide_valid = 0;
    float min_depth = 1, max_depth = 0;
    for (unsigned i = 0; i < 4096; ++i) {
      guide_valid += static_cast<const uint16_t *>(debug_guide)[i * 4 + 3] != 0;
      min_depth =
          std::min(min_depth, static_cast<const float *>(debug_depth)[i]);
      max_depth =
          std::max(max_depth, static_cast<const float *>(debug_depth)[i]);
    }
    depth_readback->Unmap(0, nullptr);
    guide_readback->Unmap(0, nullptr);
    std::fprintf(stderr, "Raster reference: depth=[%f,%f], primary hits=%u\n",
                 min_depth, max_depth, guide_valid);
    void *pixels = nullptr;
    D3D12_RANGE range{0, 64 * 256};
    require(readback->Map(0, &range, &pixels));
    void *transparent_pixels = nullptr;
    require(transparent_readback->Map(0, &range, &transparent_pixels));
    if (std::memcmp(pixels, transparent_pixels, 64 * 256) != 0)
      throw std::runtime_error(
          "Alpha-zero blended geometry changed the raster image");
    transparent_readback->Unmap(0, nullptr);
    unsigned dark = 0, white_count = 0, alpha_errors = 0;
    for (unsigned i = 0; i < 64 * 64; ++i) {
      auto *pixel = static_cast<uint8_t *>(pixels) + i * 4;
      dark += pixel[0] < 100;
      white_count += pixel[0] >= 100;
      alpha_errors += pixel[3] != 255;
    }
    readback->Unmap(0, nullptr);
    void *material_pixels = nullptr;
    D3D12_RANGE material_range{0, 512 * 16};
    require(material_readback->Map(0, &material_range, &material_pixels));
    unsigned discarded = 0, covered = 0, hdr = 0, opaque_zero_alpha = 0;
    for (unsigned tile = 0; tile < 4; ++tile)
      for (unsigned y = 1; y < 12; ++y)
        for (unsigned x = 1; x < 12 - y; ++x) {
          auto *pixel = reinterpret_cast<const uint16_t *>(
              static_cast<const uint8_t *>(material_pixels) + y * 512 +
              (tile * 16 + x) * 8);
          discarded += pixel[0] == 0xFBFF;
          covered += pixel[0] != 0xFBFF;
          hdr += pixel[0] != 0xFBFF && pixel[0] > 0x3C00 && pixel[0] < 0x7C00;
          opaque_zero_alpha += pixel[0] != 0xFBFF && pixel[3] == 0;
        }
    material_readback->Unmap(0, nullptr);
    if (!discarded || !covered || !hdr || !opaque_zero_alpha)
      throw std::runtime_error(
          "Original material shader failed cutout / HDR / opaque alpha checks");
    if (!dark || !white_count || alpha_errors)
      throw std::runtime_error("DXR image did not preserve colour and produce "
                               "local occlusion: dark=" +
                               std::to_string(dark) +
                               ", ordinary=" + std::to_string(white_count) +
                               ", alpha=" + std::to_string(alpha_errors));
    std::printf(
        "{\"native_dxr\":true,\"scene_draws\":%u,\"occluded_pixels\":%u,"
        "\"unoccluded_pixels\":%u,\"alpha_errors\":%u,\"position_register\":%u,"
        "\"legacy_signature_rejected\":%s,\"material_discarded_pixels\":%u,"
        "\"material_covered_pixels\":%u,\"hdr_material_pixels\":%u,\"opaque_"
        "zero_alpha_pixels\":%u,\"spatial_denoise_passes\":2,\"alpha_zero_"
        "blended_preserves_image\":true,\"texture_driven_cutout\":true,"
        "\"raster_depth_primary_validation\":true,\"orphan_occlusion_"
        "recovery\":true,\"querybatch_snapshots\":true,\"bounded_querybatch_wrap\":true}\n",
        captured_draws.load(), dark, white_count, alpha_errors,
        capture_layout->position_register, legacy_rejected ? "true" : "false",
        discarded, covered, hdr, opaque_zero_alpha);
    NativeRtShutdown();
    return 0;
  } catch (const std::exception &e) {
    std::fprintf(stderr, "%s\n", e.what());
    return 1;
  }
}
