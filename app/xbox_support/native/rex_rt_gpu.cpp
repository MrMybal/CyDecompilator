#include "rex_rt_gpu.h"
#include "rex_rt_api.h"
#include "rt_ambient.h"
#include "rt_capture.h"
#include "rt_capture_variants.h"
#include "rt_denoise.h"
#include <algorithm>
#include <array>
#include <cmath>
#include <cstring>
#include <d3d11shader.h>
#include <d3dcompiler.h>
#include <memory>
#include <mutex>
#include <rex/logging.h>
#include <rex/system/gpu_plugin.h>
#include <unordered_map>
#include <vector>
#include <wrl/client.h>

namespace {
using Microsoft::WRL::ComPtr;
constexpr UINT kTriangles = 131072, kVertices = kTriangles * 3;
constexpr UINT64 kVertexBytes = UINT64(kVertices) * 20;
struct TargetBindings {
  UINT count = 0;
  D3D12_CPU_DESCRIPTOR_HANDLE colours[8]{}, depth{};
  BOOL contiguous = FALSE, has_depth = FALSE;
} target_bindings;
std::atomic<bool> enabled{false};
std::atomic<float> strength{.35f}, radius{1.5f}, projection_tan{.520567f},
    projection_aspect{1.777778f};
std::atomic<int> status{0};
std::atomic<uint32_t> captured_draws{0};
std::atomic<uint64_t> rendered_frames{0};
std::atomic<uint32_t> effect_mask{1}, debug_view{0};
std::atomic<float> reflection_strength{.15f}, gi_strength{.18f};
std::mutex pipeline_mutex;
std::unordered_map<ID3D12RootSignature *, UINT> root_parameters;
struct CapturePipeline {
  D3D12_GRAPHICS_PIPELINE_STATE_DESC desc{};
  std::vector<uint8_t> vertex_shader;
  std::vector<uint8_t> pixel_shader;
  ComPtr<ID3D12RootSignature> root;
  ComPtr<ID3D12PipelineState> pipeline;
  ComPtr<ID3D12PipelineState> surface_pipeline;
  D3D12_GRAPHICS_PIPELINE_STATE_DESC surface_desc{};
  bool attempted = false;
  uint32_t position_register = 0;
  uint32_t material_flags = 0;
  bool reverse_depth = false;
};
std::unordered_map<ID3D12PipelineState *, std::shared_ptr<CapturePipeline>>
    pipelines;
void transition(ID3D12GraphicsCommandList *list, ID3D12Resource *resource,
                D3D12_RESOURCE_STATES before, D3D12_RESOURCE_STATES after) {
  if (before == after)
    return;
  D3D12_RESOURCE_BARRIER b{};
  b.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
  b.Transition = {resource, D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES, before,
                  after};
  list->ResourceBarrier(1, &b);
}
void uav_barrier(ID3D12GraphicsCommandList *list, ID3D12Resource *resource) {
  D3D12_RESOURCE_BARRIER b{};
  b.Type = D3D12_RESOURCE_BARRIER_TYPE_UAV;
  b.UAV.pResource = resource;
  list->ResourceBarrier(1, &b);
}
bool buffer(ID3D12Device *device, ComPtr<ID3D12Resource> &out, UINT64 bytes,
            D3D12_HEAP_TYPE heap_type, D3D12_RESOURCE_STATES state,
            D3D12_RESOURCE_FLAGS flags = D3D12_RESOURCE_FLAG_NONE) {
  D3D12_HEAP_PROPERTIES heap{};
  heap.Type = heap_type;
  D3D12_RESOURCE_DESC d{};
  d.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER;
  d.Width = (bytes + 255) & ~UINT64(255);
  d.Height = d.DepthOrArraySize = d.MipLevels = 1;
  d.SampleDesc.Count = 1;
  d.Layout = D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
  d.Flags = flags;
  return SUCCEEDED(device->CreateCommittedResource(
      &heap, D3D12_HEAP_FLAG_NONE, &d, state, nullptr, IID_PPV_ARGS(&out)));
}
struct State {
  ComPtr<ID3D12Device5> device;
  ComPtr<ID3D12Resource> vertices, counter, zero_upload, blas, tlas, scratch,
      instance;
  ComPtr<ID3D12RootSignature> root;
  ComPtr<ID3D12PipelineState> ray_pipeline, denoise_pipeline;
  ComPtr<ID3D12Resource> materials;
  ComPtr<ID3D12Resource> raster_depth;
  ComPtr<ID3D12DescriptorHeap> raster_dsv;
  D3D12_RESOURCE_STATES raster_depth_state = D3D12_RESOURCE_STATE_DEPTH_WRITE;
  D3D12_VIEWPORT scene_viewport{};
  SIZE_T scene_depth_handle = 0;
  bool reverse_depth = false;
  ComPtr<ID3D12DescriptorHeap> material_rtv;
  D3D12_RESOURCE_STATES material_state = D3D12_RESOURCE_STATE_RENDER_TARGET;
  D3D12_RAYTRACING_GEOMETRY_DESC geometry{};
  D3D12_BUILD_RAYTRACING_ACCELERATION_STRUCTURE_INPUTS blas_inputs{},
      tlas_inputs{};
  D3D12_RESOURCE_STATES vertex_state = D3D12_RESOURCE_STATE_COPY_DEST;
  D3D12_RESOURCE_STATES counter_state = D3D12_RESOURCE_STATE_COPY_DEST;
  bool attempted = false, ready = false, started = false;
  uint32_t draws = 0, tiles = 0;
  float tangent = .520567f, aspect = 1.777778f;
  struct Image {
    ComPtr<ID3D12Resource> colour;
    ComPtr<ID3D12Resource> effect, guide, filtered;
    D3D12_RESOURCE_STATES state = D3D12_RESOURCE_STATE_COPY_DEST;
    UINT64 width;
    UINT height;
    DXGI_FORMAT format;
  };
  std::vector<std::unique_ptr<Image>> images;
  struct Views {
    ComPtr<ID3D12Resource> output;
    ID3D12Resource *source;
    ComPtr<ID3D12DescriptorHeap> heap;
  };
  std::vector<Views> views;
  bool Initialize(ID3D12Device *d) {
    if (attempted)
      return ready;
    attempted = true;
    D3D12_FEATURE_DATA_D3D12_OPTIONS5 options{};
    if (FAILED(d->CheckFeatureSupport(D3D12_FEATURE_D3D12_OPTIONS5, &options,
                                      sizeof(options))) ||
        options.RaytracingTier < D3D12_RAYTRACING_TIER_1_1 ||
        FAILED(d->QueryInterface(IID_PPV_ARGS(&device)))) {
      status.store(-1);
      REXLOG_WARN("[native-rt] DXR 1.1 is unavailable on this adapter");
      return false;
    }
    status.store(1);
    if (!buffer(d, vertices, kVertexBytes, D3D12_HEAP_TYPE_DEFAULT,
                vertex_state) ||
        !buffer(d, counter, 8, D3D12_HEAP_TYPE_DEFAULT, counter_state) ||
        !buffer(d, zero_upload, kVertexBytes, D3D12_HEAP_TYPE_UPLOAD,
                D3D12_RESOURCE_STATE_GENERIC_READ))
      return Fail();
    void *mapped = nullptr;
    D3D12_RANGE empty{};
    if (FAILED(zero_upload->Map(0, &empty, &mapped)))
      return Fail();
    std::memset(mapped, 0, size_t(kVertexBytes));
    zero_upload->Unmap(0, nullptr);
    geometry.Type = D3D12_RAYTRACING_GEOMETRY_TYPE_TRIANGLES;
    geometry.Flags = D3D12_RAYTRACING_GEOMETRY_FLAG_NONE;
    geometry.Triangles.VertexFormat = DXGI_FORMAT_R32G32B32_FLOAT;
    geometry.Triangles.VertexCount = kVertices;
    geometry.Triangles.VertexBuffer = {vertices->GetGPUVirtualAddress(), 20};
    blas_inputs.Type =
        D3D12_RAYTRACING_ACCELERATION_STRUCTURE_TYPE_BOTTOM_LEVEL;
    blas_inputs.Flags =
        D3D12_RAYTRACING_ACCELERATION_STRUCTURE_BUILD_FLAG_PREFER_FAST_BUILD;
    blas_inputs.DescsLayout = D3D12_ELEMENTS_LAYOUT_ARRAY;
    blas_inputs.NumDescs = 1;
    blas_inputs.pGeometryDescs = &geometry;
    tlas_inputs.Type = D3D12_RAYTRACING_ACCELERATION_STRUCTURE_TYPE_TOP_LEVEL;
    tlas_inputs.Flags =
        D3D12_RAYTRACING_ACCELERATION_STRUCTURE_BUILD_FLAG_PREFER_FAST_TRACE;
    tlas_inputs.DescsLayout = D3D12_ELEMENTS_LAYOUT_ARRAY;
    tlas_inputs.NumDescs = 1;
    D3D12_RAYTRACING_ACCELERATION_STRUCTURE_PREBUILD_INFO b{}, t{};
    device->GetRaytracingAccelerationStructurePrebuildInfo(&blas_inputs, &b);
    device->GetRaytracingAccelerationStructurePrebuildInfo(&tlas_inputs, &t);
    if (!b.ResultDataMaxSizeInBytes || !t.ResultDataMaxSizeInBytes ||
        !buffer(d, blas, b.ResultDataMaxSizeInBytes, D3D12_HEAP_TYPE_DEFAULT,
                D3D12_RESOURCE_STATE_RAYTRACING_ACCELERATION_STRUCTURE,
                D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS) ||
        !buffer(d, tlas, t.ResultDataMaxSizeInBytes, D3D12_HEAP_TYPE_DEFAULT,
                D3D12_RESOURCE_STATE_RAYTRACING_ACCELERATION_STRUCTURE,
                D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS) ||
        !buffer(d, scratch,
                std::max(b.ScratchDataSizeInBytes, t.ScratchDataSizeInBytes),
                D3D12_HEAP_TYPE_DEFAULT, D3D12_RESOURCE_STATE_UNORDERED_ACCESS,
                D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS) ||
        !buffer(d, instance, sizeof(D3D12_RAYTRACING_INSTANCE_DESC),
                D3D12_HEAP_TYPE_UPLOAD, D3D12_RESOURCE_STATE_GENERIC_READ))
      return Fail();
    if (FAILED(instance->Map(0, &empty, &mapped)))
      return Fail();
    D3D12_RAYTRACING_INSTANCE_DESC inst{};
    inst.Transform[0][0] = inst.Transform[1][1] = inst.Transform[2][2] = 1;
    inst.InstanceMask = 0xFF;
    inst.AccelerationStructure = blas->GetGPUVirtualAddress();
    std::memcpy(mapped, &inst, sizeof(inst));
    instance->Unmap(0, nullptr);
    tlas_inputs.InstanceDescs = instance->GetGPUVirtualAddress();
    D3D12_RESOURCE_DESC atlas{};
    atlas.Dimension = D3D12_RESOURCE_DIMENSION_TEXTURE2D;
    atlas.Width = 4096;
    atlas.Height = 8192;
    atlas.DepthOrArraySize = atlas.MipLevels = atlas.SampleDesc.Count = 1;
    atlas.Format = DXGI_FORMAT_R16G16B16A16_FLOAT;
    atlas.Flags = D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET;
    D3D12_HEAP_PROPERTIES default_heap{};
    default_heap.Type = D3D12_HEAP_TYPE_DEFAULT;
    if (FAILED(d->CreateCommittedResource(&default_heap, D3D12_HEAP_FLAG_NONE,
                                          &atlas, material_state, nullptr,
                                          IID_PPV_ARGS(&materials))))
      return Fail();
    D3D12_DESCRIPTOR_HEAP_DESC rh{D3D12_DESCRIPTOR_HEAP_TYPE_RTV, 1,
                                  D3D12_DESCRIPTOR_HEAP_FLAG_NONE, 0};
    if (FAILED(d->CreateDescriptorHeap(&rh, IID_PPV_ARGS(&material_rtv))))
      return Fail();
    d->CreateRenderTargetView(
        materials.Get(), nullptr,
        material_rtv->GetCPUDescriptorHandleForHeapStart());
    auto depth_desc = atlas;
    depth_desc.Width = depth_desc.Height = 2048;
    depth_desc.Format = DXGI_FORMAT_R32_TYPELESS;
    depth_desc.Flags = D3D12_RESOURCE_FLAG_ALLOW_DEPTH_STENCIL;
    if (FAILED(d->CreateCommittedResource(
            &default_heap, D3D12_HEAP_FLAG_NONE, &depth_desc,
            raster_depth_state, nullptr, IID_PPV_ARGS(&raster_depth))))
      return Fail();
    D3D12_DESCRIPTOR_HEAP_DESC dh{D3D12_DESCRIPTOR_HEAP_TYPE_DSV, 1,
                                  D3D12_DESCRIPTOR_HEAP_FLAG_NONE, 0};
    if (FAILED(d->CreateDescriptorHeap(&dh, IID_PPV_ARGS(&raster_dsv))))
      return Fail();
    D3D12_DEPTH_STENCIL_VIEW_DESC dv{};
    dv.Format = DXGI_FORMAT_D32_FLOAT;
    dv.ViewDimension = D3D12_DSV_DIMENSION_TEXTURE2D;
    d->CreateDepthStencilView(raster_depth.Get(), &dv,
                              raster_dsv->GetCPUDescriptorHandleForHeapStart());
    D3D12_DESCRIPTOR_RANGE ranges[2] = {
        {D3D12_DESCRIPTOR_RANGE_TYPE_SRV, 6, 2, 0, 0},
        {D3D12_DESCRIPTOR_RANGE_TYPE_UAV, 4, 0, 0, 0}};
    D3D12_ROOT_PARAMETER p[5]{};
    p[0].ParameterType = D3D12_ROOT_PARAMETER_TYPE_32BIT_CONSTANTS;
    p[0].Constants = {0, 0, 20};
    for (int i = 1; i <= 2; ++i) {
      p[i].ParameterType = D3D12_ROOT_PARAMETER_TYPE_SRV;
      p[i].Descriptor = {UINT(i - 1), 0};
    }
    for (int i = 3; i <= 4; ++i) {
      p[i].ParameterType = D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE;
      p[i].DescriptorTable = {1, &ranges[i - 3]};
    }
    D3D12_ROOT_SIGNATURE_DESC rd{5, p, 0, nullptr,
                                 D3D12_ROOT_SIGNATURE_FLAG_NONE};
    ComPtr<ID3DBlob> serialized, errors;
    if (FAILED(D3D12SerializeRootSignature(&rd, D3D_ROOT_SIGNATURE_VERSION_1,
                                           &serialized, &errors)) ||
        FAILED(d->CreateRootSignature(0, serialized->GetBufferPointer(),
                                      serialized->GetBufferSize(),
                                      IID_PPV_ARGS(&root))))
      return Fail();
    D3D12_COMPUTE_PIPELINE_STATE_DESC cp{};
    cp.pRootSignature = root.Get();
    cp.CS = {native_rt_ambient, sizeof(native_rt_ambient)};
    if (FAILED(d->CreateComputePipelineState(&cp, IID_PPV_ARGS(&ray_pipeline))))
      return Fail();
    cp.CS = {native_rt_denoise, sizeof(native_rt_denoise)};
    if (FAILED(d->CreateComputePipelineState(&cp,
                                             IID_PPV_ARGS(&denoise_pipeline))))
      return Fail();
    ready = true;
    REXLOG_INFO("[native-rt] DXR 1.1 native ambient occlusion initialized; {} "
                "triangle slots",
                kVertices / 3);
    return true;
  }
  bool Fail() {
    status.store(-2);
    REXLOG_WARN("[native-rt] Initialization failed; preserving ordinary raster "
                "rendering");
    return false;
  }
  void Begin(ID3D12GraphicsCommandList *list, const NativeRtDraw &draw,
             bool reversed) {
    reverse_depth = reversed;
    scene_viewport = draw.viewport;
    scene_depth_handle =
        target_bindings.has_depth ? target_bindings.depth.ptr : 0;
    transition(list, raster_depth.Get(), raster_depth_state,
               D3D12_RESOURCE_STATE_DEPTH_WRITE);
    raster_depth_state = D3D12_RESOURCE_STATE_DEPTH_WRITE;
    list->ClearDepthStencilView(
        raster_dsv->GetCPUDescriptorHandleForHeapStart(),
        D3D12_CLEAR_FLAG_DEPTH, reversed ? 0.f : 1.f, 0, 0, nullptr);
    transition(list, materials.Get(), material_state,
               D3D12_RESOURCE_STATE_RENDER_TARGET);
    material_state = D3D12_RESOURCE_STATE_RENDER_TARGET;
    // Sentinel independent of shader alpha: opaque materials may output
    // alpha=0.
    const float empty_material[4] = {-65504, -65504, -65504, -65504};
    list->ClearRenderTargetView(
        material_rtv->GetCPUDescriptorHandleForHeapStart(), empty_material, 0,
        nullptr);
    transition(list, vertices.Get(), vertex_state,
               D3D12_RESOURCE_STATE_COPY_DEST);
    transition(list, counter.Get(), counter_state,
               D3D12_RESOURCE_STATE_COPY_DEST);
    list->CopyBufferRegion(vertices.Get(), 0, zero_upload.Get(), 0,
                           kVertexBytes);
    list->CopyBufferRegion(counter.Get(), 0, zero_upload.Get(), 0, 8);
    transition(list, vertices.Get(), D3D12_RESOURCE_STATE_COPY_DEST,
               D3D12_RESOURCE_STATE_STREAM_OUT);
    transition(list, counter.Get(), D3D12_RESOURCE_STATE_COPY_DEST,
               D3D12_RESOURCE_STATE_STREAM_OUT);
    vertex_state = counter_state = D3D12_RESOURCE_STATE_STREAM_OUT;
    tangent = projection_tan.load();
    aspect = projection_aspect.load();
    started = true;
    draws = 0;
    tiles = 0;
  }
  Image *GetImage(ID3D12Resource *output) {
    auto desc = output->GetDesc();
    for (auto &image : images)
      if (image->width == desc.Width && image->height == desc.Height &&
          image->format == desc.Format)
        return image.get();
    auto image = std::make_unique<Image>();
    image->width = desc.Width;
    image->height = desc.Height;
    image->format = desc.Format;
    desc.Flags = D3D12_RESOURCE_FLAG_NONE;
    D3D12_HEAP_PROPERTIES heap{};
    heap.Type = D3D12_HEAP_TYPE_DEFAULT;
    if (FAILED(device->CreateCommittedResource(&heap, D3D12_HEAP_FLAG_NONE,
                                               &desc, image->state, nullptr,
                                               IID_PPV_ARGS(&image->colour))))
      return nullptr;
    desc.Format = DXGI_FORMAT_R16G16B16A16_FLOAT;
    desc.Flags = D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS;
    for (auto *resource :
         {std::addressof(image->effect), std::addressof(image->guide),
          std::addressof(image->filtered)})
      if (FAILED(device->CreateCommittedResource(
              &heap, D3D12_HEAP_FLAG_NONE, &desc,
              D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE, nullptr,
              IID_PPV_ARGS(resource->ReleaseAndGetAddressOf()))))
        return nullptr;
    auto result = image.get();
    images.push_back(std::move(image));
    return result;
  }
  ID3D12DescriptorHeap *GetViews(ID3D12Resource *output, Image &image) {
    for (auto &v : views)
      if (v.output.Get() == output && v.source == image.colour.Get())
        return v.heap.Get();
    Views v{};
    v.output = output;
    v.source = image.colour.Get();
    D3D12_DESCRIPTOR_HEAP_DESC hd{D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV, 10,
                                  D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE, 0};
    if (FAILED(device->CreateDescriptorHeap(&hd, IID_PPV_ARGS(&v.heap))))
      return nullptr;
    auto cpu = v.heap->GetCPUDescriptorHandleForHeapStart();
    D3D12_SHADER_RESOURCE_VIEW_DESC srv{};
    srv.Format = image.format;
    srv.ViewDimension = D3D12_SRV_DIMENSION_TEXTURE2D;
    srv.Shader4ComponentMapping = D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;
    srv.Texture2D.MipLevels = 1;
    UINT stride = device->GetDescriptorHandleIncrementSize(hd.Type);
    ID3D12Resource *sources[] = {image.colour.Get(),   materials.Get(),
                                 image.effect.Get(),   image.guide.Get(),
                                 image.filtered.Get(), raster_depth.Get()};
    for (auto *source : sources) {
      srv.Format = source->GetDesc().Format;
      if (source == raster_depth.Get())
        srv.Format = DXGI_FORMAT_R32_FLOAT;
      device->CreateShaderResourceView(source, &srv, cpu);
      cpu.ptr += stride;
    }
    D3D12_UNORDERED_ACCESS_VIEW_DESC u{};
    u.ViewDimension = D3D12_UAV_DIMENSION_TEXTURE2D;
    ID3D12Resource *destinations[] = {output, image.effect.Get(),
                                      image.guide.Get(), image.filtered.Get()};
    for (auto *destination : destinations) {
      u.Format = destination->GetDesc().Format;
      device->CreateUnorderedAccessView(destination, nullptr, &u, cpu);
      cpu.ptr += stride;
    }
    auto result = v.heap.Get();
    views.push_back(std::move(v));
    return result;
  }
};
std::unique_ptr<State> rt;
} // namespace

bool NativeRtEnabled() { return enabled.load(); }
void NativeRtRememberTargets(UINT count,
                             const D3D12_CPU_DESCRIPTOR_HANDLE *colours,
                             BOOL contiguous,
                             const D3D12_CPU_DESCRIPTOR_HANDLE *depth) {
  target_bindings.count = std::min(count, 8u);
  target_bindings.contiguous = contiguous;
  if (count)
    std::copy_n(colours, contiguous ? 1 : target_bindings.count,
                target_bindings.colours);
  target_bindings.has_depth = depth != nullptr;
  if (depth)
    target_bindings.depth = *depth;
}
ID3D12RootSignature *
NativeRtCreateRoot(const rex::ui::d3d12::D3D12Provider &provider,
                   const D3D12_ROOT_SIGNATURE_DESC &original) {
  std::vector<D3D12_ROOT_PARAMETER> parameters(
      original.pParameters, original.pParameters + original.NumParameters);
  D3D12_ROOT_PARAMETER extra{};
  extra.ParameterType = D3D12_ROOT_PARAMETER_TYPE_32BIT_CONSTANTS;
  extra.Constants = {15, 15, 8};
  extra.ShaderVisibility = D3D12_SHADER_VISIBILITY_GEOMETRY;
  parameters.push_back(extra);
  auto desc = original;
  desc.pParameters = parameters.data();
  desc.NumParameters = UINT(parameters.size());
  desc.Flags |= D3D12_ROOT_SIGNATURE_FLAG_ALLOW_STREAM_OUTPUT;
  auto *root = rex::ui::d3d12::util::CreateRootSignature(provider, desc);
  if (root) {
    std::lock_guard lock(pipeline_mutex);
    root_parameters[root] = original.NumParameters;
  }
  return root;
}
void NativeRtRegisterPipeline(ID3D12Device *,
                              const D3D12_GRAPHICS_PIPELINE_STATE_DESC &desc,
                              ID3D12PipelineState *original) {
  if (desc.PrimitiveTopologyType != D3D12_PRIMITIVE_TOPOLOGY_TYPE_TRIANGLE ||
      desc.HS.BytecodeLength || desc.DS.BytecodeLength ||
      desc.GS.BytecodeLength || !desc.VS.BytecodeLength)
    return;
  // ROV/memexport pixel shaders have side effects and must never be replayed.
  if (!desc.PS.BytecodeLength || !desc.NumRenderTargets ||
      desc.RTVFormats[0] == DXGI_FORMAT_UNKNOWN)
    return;
  ComPtr<ID3D11ShaderReflection> ps_reflection;
  if (FAILED(D3DReflect(desc.PS.pShaderBytecode, desc.PS.BytecodeLength,
                        IID_PPV_ARGS(&ps_reflection))))
    return;
  D3D11_SHADER_DESC ps_desc{};
  ps_reflection->GetDesc(&ps_desc);
  for (UINT i = 0; i < ps_desc.BoundResources; ++i) {
    D3D11_SHADER_INPUT_BIND_DESC binding{};
    ps_reflection->GetResourceBindingDesc(i, &binding);
    if (binding.Type == D3D_SIT_UAV_RWTYPED ||
        binding.Type == D3D_SIT_UAV_RWSTRUCTURED ||
        binding.Type == D3D_SIT_UAV_RWBYTEADDRESS ||
        binding.Type >= D3D_SIT_UAV_APPEND_STRUCTURED)
      return;
  }
  std::lock_guard lock(pipeline_mutex);
  if (!root_parameters.contains(desc.pRootSignature))
    return;
  auto p = std::make_shared<CapturePipeline>();
  p->desc = desc;
  p->root = desc.pRootSignature;
  auto *bytes = static_cast<const uint8_t *>(desc.VS.pShaderBytecode);
  p->vertex_shader.assign(bytes, bytes + desc.VS.BytecodeLength);
  auto *ps = static_cast<const uint8_t *>(desc.PS.pShaderBytecode);
  p->pixel_shader.assign(ps, ps + desc.PS.BytecodeLength);
  p->desc.PS = {p->pixel_shader.data(), p->pixel_shader.size()};
  const auto &blend = desc.BlendState.RenderTarget[0];
  if (blend.BlendEnable) {
    p->material_flags |= 1;
    if (blend.DestBlend == D3D12_BLEND_ONE &&
        blend.BlendOp == D3D12_BLEND_OP_ADD)
      p->material_flags |= 2;
    if (blend.SrcBlend == D3D12_BLEND_ONE &&
        blend.DestBlend == D3D12_BLEND_INV_SRC_ALPHA)
      p->material_flags |= 4;
    if ((p->material_flags & 2) && blend.SrcBlend == D3D12_BLEND_SRC_ALPHA)
      p->material_flags |= 8;
  }
  p->desc.VS = {p->vertex_shader.data(), p->vertex_shader.size()};
  ComPtr<ID3D11ShaderReflection> reflection;
  if (FAILED(D3DReflect(p->vertex_shader.data(), p->vertex_shader.size(),
                        IID_PPV_ARGS(&reflection))))
    return;
  D3D11_SHADER_DESC shader_desc{};
  reflection->GetDesc(&shader_desc);
  bool found_position = false;
  for (UINT i = 0; i < shader_desc.OutputParameters; ++i) {
    D3D11_SIGNATURE_PARAMETER_DESC parameter{};
    reflection->GetOutputParameterDesc(i, &parameter);
    if (parameter.SystemValueType == D3D_NAME_POSITION) {
      p->position_register = parameter.Register;
      found_position = true;
    }
  }
  if (!found_position ||
      p->position_register >= std::size(native_capture_variants))
    return;
  auto capture_shader = native_capture_variants[p->position_register];
  p->desc.GS = {capture_shader.data, capture_shader.size};
  p->desc.CachedPSO = {};
  p->desc.NumRenderTargets = 1;
  std::fill(std::begin(p->desc.RTVFormats), std::end(p->desc.RTVFormats),
            DXGI_FORMAT_UNKNOWN);
  p->desc.RTVFormats[0] = DXGI_FORMAT_R16G16B16A16_FLOAT;
  for (auto &target : p->desc.BlendState.RenderTarget) {
    target.BlendEnable = target.LogicOpEnable = FALSE;
    target.RenderTargetWriteMask = 0;
  }
  p->desc.BlendState.RenderTarget[0].RenderTargetWriteMask = 15;
  p->desc.BlendState.AlphaToCoverageEnable = FALSE;
  p->desc.DSVFormat = DXGI_FORMAT_UNKNOWN;
  p->desc.DepthStencilState.DepthEnable =
      p->desc.DepthStencilState.StencilEnable = FALSE;
  p->desc.RasterizerState.CullMode = D3D12_CULL_MODE_NONE;
  p->desc.RasterizerState.ForcedSampleCount = 0;
  p->desc.RasterizerState.DepthClipEnable = FALSE;
  p->desc.RasterizerState.DepthBias = 0;
  p->desc.RasterizerState.SlopeScaledDepthBias = 0;
  p->desc.SampleDesc = {1, 0};
  p->desc.SampleMask = UINT_MAX;
  p->reverse_depth =
      desc.DepthStencilState.DepthFunc == D3D12_COMPARISON_FUNC_GREATER ||
      desc.DepthStencilState.DepthFunc == D3D12_COMPARISON_FUNC_GREATER_EQUAL;
  p->surface_desc = p->desc;
  auto surface_shader = native_surface_variants[p->position_register];
  p->surface_desc.GS = {surface_shader.data, surface_shader.size};
  p->surface_desc.NumRenderTargets = 0;
  p->surface_desc.RTVFormats[0] = DXGI_FORMAT_UNKNOWN;
  p->surface_desc.DSVFormat = DXGI_FORMAT_D32_FLOAT;
  p->surface_desc.DepthStencilState.DepthEnable = TRUE;
  p->surface_desc.DepthStencilState.DepthWriteMask = D3D12_DEPTH_WRITE_MASK_ALL;
  p->surface_desc.DepthStencilState.DepthFunc =
      p->reverse_depth ? D3D12_COMPARISON_FUNC_GREATER_EQUAL
                       : D3D12_COMPARISON_FUNC_LESS_EQUAL;
  p->surface_desc.RasterizerState.CullMode = desc.RasterizerState.CullMode;
  p->surface_desc.RasterizerState.DepthClipEnable = TRUE;
  pipelines[original] = std::move(p);
}
void NativeRtCapture(ID3D12GraphicsCommandList *list, const void *data) {
  if (!enabled.load())
    return;
  const auto &draw = *static_cast<const NativeRtDraw *>(data);
  if (!draw.pipeline || !draw.root || !draw.count || !draw.triangles)
    return;
  // Shadows, probes and UI may use unrelated projection matrices. Keep one
  // perspective viewport/depth target, rather than overlaying all those views.
  float expected_aspect = projection_aspect.load();
  if (draw.viewport.Width < 16 || draw.viewport.Height < 16 ||
      draw.viewport.TopLeftX < 0 || draw.viewport.TopLeftY < 0 ||
      draw.viewport.TopLeftX + draw.viewport.Width > 2048 ||
      draw.viewport.TopLeftY + draw.viewport.Height > 2048 ||
      std::abs(draw.viewport.Width / draw.viewport.Height / expected_aspect -
               1.f) > .06f ||
      draw.viewport.MaxDepth - draw.viewport.MinDepth < .5f)
    return;
  std::shared_ptr<CapturePipeline> pipeline;
  UINT parameter;
  {
    std::lock_guard lock(pipeline_mutex);
    auto p = pipelines.find(draw.pipeline);
    auto r = root_parameters.find(draw.root);
    if (p == pipelines.end() || r == root_parameters.end())
      return;
    pipeline = p->second;
    parameter = r->second;
  }
  if (!rt)
    rt = std::make_unique<State>();
  if (!rt->Initialize(draw.device))
    return;
  if (!pipeline->attempted) {
    pipeline->attempted = true;
    D3D12_SO_DECLARATION_ENTRY entries[] = {{0, "TEXCOORD", 16, 0, 4, 0},
                                            {0, "TEXCOORD", 17, 0, 1, 0}};
    UINT stride = 20;
    auto desc = pipeline->desc;
    desc.StreamOutput = {entries, 2, &stride, 1, 0};
    HRESULT hr = draw.device->CreateGraphicsPipelineState(
        &desc, IID_PPV_ARGS(&pipeline->pipeline));
    if (FAILED(hr)) {
      status.store(-3);
      REXLOG_WARN("[native-rt] Triangle capture pipeline rejected: {:08X}, "
                  "position register={}",
                  uint32_t(hr), pipeline->position_register);
    }
    if (SUCCEEDED(hr)) {
      hr = draw.device->CreateGraphicsPipelineState(
          &pipeline->surface_desc, IID_PPV_ARGS(&pipeline->surface_pipeline));
      if (FAILED(hr)) {
        status.store(-3);
        REXLOG_WARN("[native-rt] Raster surface pipeline rejected: {:08X}",
                    uint32_t(hr));
      }
    }
  }
  if (!pipeline->pipeline || !pipeline->surface_pipeline)
    return;
  if (!rt->started)
    rt->Begin(list, draw, pipeline->reverse_depth);
  if (std::abs(draw.viewport.Width - rt->scene_viewport.Width) > 1 ||
      std::abs(draw.viewport.Height - rt->scene_viewport.Height) > 1 ||
      (target_bindings.has_depth ? target_bindings.depth.ptr : 0) !=
          rt->scene_depth_handle)
    return;
  if (draw.triangles > kTriangles - rt->tiles)
    return;
  float constants[8] = {draw.scale[0],
                        draw.scale[1],
                        float(rt->tiles),
                        rt->tangent,
                        draw.offset[0],
                        draw.offset[1],
                        float(draw.material_flags | pipeline->material_flags),
                        rt->aspect};
  auto atlas_rtv = rt->material_rtv->GetCPUDescriptorHandleForHeapStart();
  list->OMSetRenderTargets(1, &atlas_rtv, FALSE, nullptr);
  D3D12_VIEWPORT atlas_view{0, 0, 4096, 8192, 0, 1};
  D3D12_RECT atlas_scissor{0, 0, 4096, 8192};
  list->RSSetViewports(1, &atlas_view);
  list->RSSetScissorRects(1, &atlas_scissor);
  list->SetGraphicsRoot32BitConstants(parameter, 8, constants, 0);
  list->SetPipelineState(pipeline->pipeline.Get());
  D3D12_STREAM_OUTPUT_BUFFER_VIEW view{rt->vertices->GetGPUVirtualAddress(),
                                       kVertexBytes,
                                       rt->counter->GetGPUVirtualAddress()};
  list->SOSetTargets(0, 1, &view);
  if (draw.indexed)
    list->DrawIndexedInstanced(draw.count, 1, 0, 0, 0);
  else
    list->DrawInstanced(draw.count, 1, 0, 0);
  list->SOSetTargets(0, 0, nullptr);
  if (!(pipeline->material_flags & 1)) {
    // Original screen coordinates and original alpha-test shader provide a
    // full-resolution primary visibility reference, independent of the atlas.
    auto depth = rt->raster_dsv->GetCPUDescriptorHandleForHeapStart();
    list->OMSetRenderTargets(0, nullptr, FALSE, &depth);
    list->RSSetViewports(1, &draw.viewport);
    list->RSSetScissorRects(1, &draw.scissor);
    list->SetPipelineState(pipeline->surface_pipeline.Get());
    if (draw.indexed)
      list->DrawIndexedInstanced(draw.count, 1, 0, 0, 0);
    else
      list->DrawInstanced(draw.count, 1, 0, 0);
  }
  list->SetPipelineState(draw.pipeline);
  list->OMSetRenderTargets(target_bindings.count, target_bindings.colours,
                           target_bindings.contiguous,
                           target_bindings.has_depth ? &target_bindings.depth
                                                     : nullptr);
  list->RSSetViewports(1, &draw.viewport);
  list->RSSetScissorRects(1, &draw.scissor);
  rt->tiles += draw.triangles;
  ++rt->draws;
}
void NativeRtComposite(ID3D12GraphicsCommandList *list, const void *data) {
  if (!rt || !rt->started) {
    captured_draws.store(0);
    return;
  }
  rt->started = false;
  captured_draws.store(rt->draws);
  if (!enabled.load() || !rt->ready || !rt->draws)
    return;
  const auto &present = *static_cast<const NativeRtPresent *>(data);
  auto *image = rt->GetImage(present.output);
  auto *heap = image ? rt->GetViews(present.output, *image) : nullptr;
  ComPtr<ID3D12GraphicsCommandList4> dxr;
  if (!heap || FAILED(list->QueryInterface(IID_PPV_ARGS(&dxr)))) {
    rt->Fail();
    return;
  }
  transition(list, rt->vertices.Get(), rt->vertex_state,
             D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
  rt->vertex_state = D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE;
  transition(list, rt->materials.Get(), rt->material_state,
             D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
  rt->material_state = D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE;
  transition(list, rt->raster_depth.Get(), rt->raster_depth_state,
             D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
  rt->raster_depth_state = D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE;
  transition(list, image->effect.Get(),
             D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,
             D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
  transition(list, image->guide.Get(),
             D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,
             D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
  D3D12_BUILD_RAYTRACING_ACCELERATION_STRUCTURE_DESC build{};
  build.Inputs = rt->blas_inputs;
  build.DestAccelerationStructureData = rt->blas->GetGPUVirtualAddress();
  build.ScratchAccelerationStructureData = rt->scratch->GetGPUVirtualAddress();
  uav_barrier(list, rt->blas.Get());
  uav_barrier(list, rt->tlas.Get());
  uav_barrier(list, rt->scratch.Get());
  dxr->BuildRaytracingAccelerationStructure(&build, 0, nullptr);
  uav_barrier(list, rt->blas.Get());
  uav_barrier(list, rt->scratch.Get());
  build.Inputs = rt->tlas_inputs;
  build.DestAccelerationStructureData = rt->tlas->GetGPUVirtualAddress();
  dxr->BuildRaytracingAccelerationStructure(&build, 0, nullptr);
  uav_barrier(list, rt->tlas.Get());
  transition(list, present.output, present.state,
             D3D12_RESOURCE_STATE_COPY_SOURCE);
  transition(list, image->colour.Get(), image->state,
             D3D12_RESOURCE_STATE_COPY_DEST);
  list->CopyResource(image->colour.Get(), present.output);
  transition(list, image->colour.Get(), D3D12_RESOURCE_STATE_COPY_DEST,
             D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
  image->state = D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE;
  transition(list, present.output, D3D12_RESOURCE_STATE_COPY_SOURCE,
             D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
  struct {
    uint32_t width, height;
    float tangent, aspect, strength, radius;
    uint32_t rays, debug, effects;
    float reflections, indirect, roughness;
    float viewport[4], depth_min, depth_scale, padding[2];
  } constants{UINT(image->width),
              image->height,
              rt->tangent,
              rt->aspect,
              strength.load(),
              radius.load(),
              8,
              debug_view.load(),
              effect_mask.load(),
              reflection_strength.load(),
              gi_strength.load(),
              .25f,
              {rt->scene_viewport.TopLeftX, rt->scene_viewport.TopLeftY,
               rt->scene_viewport.Width, rt->scene_viewport.Height},
              rt->scene_viewport.MinDepth,
              rt->scene_viewport.MaxDepth - rt->scene_viewport.MinDepth,
              {rt->reverse_depth ? 1.f : 0.f, 0}};
  list->SetDescriptorHeaps(1, &heap);
  list->SetComputeRootSignature(rt->root.Get());
  list->SetPipelineState(rt->ray_pipeline.Get());
  list->SetComputeRoot32BitConstants(0, 20, &constants, 0);
  list->SetComputeRootShaderResourceView(1, rt->tlas->GetGPUVirtualAddress());
  list->SetComputeRootShaderResourceView(2,
                                         rt->vertices->GetGPUVirtualAddress());
  auto gpu = heap->GetGPUDescriptorHandleForHeapStart();
  list->SetComputeRootDescriptorTable(3, gpu);
  gpu.ptr += 6 * rt->device->GetDescriptorHandleIncrementSize(
                     D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
  list->SetComputeRootDescriptorTable(4, gpu);
  list->Dispatch((constants.width + 7) / 8, (constants.height + 7) / 8, 1);
  transition(list, image->effect.Get(), D3D12_RESOURCE_STATE_UNORDERED_ACCESS,
             D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
  transition(list, image->guide.Get(), D3D12_RESOURCE_STATE_UNORDERED_ACCESS,
             D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
  transition(list, image->filtered.Get(),
             D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,
             D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
  list->SetPipelineState(rt->denoise_pipeline.Get());
  constants.rays = 0; // denoiser pass index occupies the same DWORD
  list->SetComputeRoot32BitConstants(0, 20, &constants, 0);
  list->Dispatch((constants.width + 7) / 8, (constants.height + 7) / 8, 1);
  transition(list, image->filtered.Get(), D3D12_RESOURCE_STATE_UNORDERED_ACCESS,
             D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
  constants.rays = 1;
  list->SetComputeRoot32BitConstants(0, 20, &constants, 0);
  list->Dispatch((constants.width + 7) / 8, (constants.height + 7) / 8, 1);
  transition(list, present.output, D3D12_RESOURCE_STATE_UNORDERED_ACCESS,
             present.state);
  auto frames = rendered_frames.fetch_add(1) + 1;
  status.store(2);
  if (frames == 1)
    REXLOG_INFO("[native-rt] Native DXR material capture + bilateral denoise "
                "submitted: {} scene draws, {} triangle material tiles",
                rt->draws, rt->tiles);
}
void NativeRtShutdown() {
  rt.reset();
  std::lock_guard lock(pipeline_mutex);
  pipelines.clear();
  root_parameters.clear();
}
extern "C" REX_GPU_PLUGIN_EXPORT void
rex_gpu_set_raytracing(int mode, float intensity, float distance) {
  strength.store(std::clamp(intensity, 0.f, 1.f));
  radius.store(std::clamp(distance, .05f, 10.f));
  enabled.store(mode == 1 || mode == 2);
  debug_view.store(mode == 2 ? 1 : 0);
  if (mode == 0)
    status.store(0);
}
extern "C" REX_GPU_PLUGIN_EXPORT void
rex_gpu_set_rt_effects(uint32_t effects, float reflections, float indirect) {
  effect_mask.store(effects & 7u);
  reflection_strength.store(
      std::isfinite(reflections) ? std::clamp(reflections, 0.f, 1.f) : .15f);
  gi_strength.store(std::isfinite(indirect) ? std::clamp(indirect, 0.f, 1.f)
                                            : .18f);
}
extern "C" REX_GPU_PLUGIN_EXPORT void rex_gpu_set_rt_projection(float fov,
                                                                float aspect) {
  if (std::isfinite(fov) && fov > .05f && fov < 3.f)
    projection_tan.store(std::tan(fov * .5f));
  if (std::isfinite(aspect) && aspect > .2f && aspect < 5.f)
    projection_aspect.store(aspect);
}
extern "C" REX_GPU_PLUGIN_EXPORT void
rex_gpu_get_rt_status(NativeRtStatus *out) {
  if (out)
    *out = {status.load(), captured_draws.load(), rendered_frames.load()};
}
