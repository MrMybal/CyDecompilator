#pragma once
// Included by the locally built GPU plugin only; the SDK stays unchanged.
#include "AreaTex.h"
#include "SearchTex.h"
#include "smaa_blend.h"
#include "smaa_edges.h"
#include "smaa_weights.h"

namespace {
struct NativeSmaaResources {
  Microsoft::WRL::ComPtr<ID3D12RootSignature> root;
  Microsoft::WRL::ComPtr<ID3D12PipelineState> pipelines[3];
  Microsoft::WRL::ComPtr<ID3D12Resource> edges, weights, area, search,
      uploads[2];
  uint32_t width = 0, height = 0;
  uint64_t submission = 0;
  bool uploaded = false;
  bool Initialize(const rex::ui::d3d12::D3D12Provider &provider) {
    auto *device = provider.GetDevice();
    D3D12_DESCRIPTOR_RANGE ranges[6]{};
    ranges[0] = {D3D12_DESCRIPTOR_RANGE_TYPE_UAV, 1, 0, 0, 0};
    for (int i=0;i<5;++i)
      ranges[i+1] = {D3D12_DESCRIPTOR_RANGE_TYPE_SRV, 1, UINT(i), 0, 0};
    D3D12_ROOT_PARAMETER parameters[7]{};
    parameters[0].ParameterType = D3D12_ROOT_PARAMETER_TYPE_32BIT_CONSTANTS;
    parameters[0].Constants = {0, 0, 4};
    for (int i = 1; i < 7; ++i) {
      parameters[i].ParameterType = D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE;
      parameters[i].DescriptorTable = {1, &ranges[i - 1]};
    }
    D3D12_STATIC_SAMPLER_DESC samplers[2]{};
    for (int i = 0; i < 2; ++i) {
      auto &s = samplers[i];
      s.Filter = i ? D3D12_FILTER_MIN_MAG_MIP_POINT
                   : D3D12_FILTER_MIN_MAG_LINEAR_MIP_POINT;
      s.AddressU = s.AddressV = s.AddressW = D3D12_TEXTURE_ADDRESS_MODE_CLAMP;
      s.MaxLOD = D3D12_FLOAT32_MAX;
      s.ComparisonFunc = D3D12_COMPARISON_FUNC_ALWAYS;
      s.MaxAnisotropy = 1;
      s.ShaderRegister = i;
    }
    D3D12_ROOT_SIGNATURE_DESC desc{7, parameters, 2, samplers,
                                   D3D12_ROOT_SIGNATURE_FLAG_NONE};
    root.Attach(rex::ui::d3d12::util::CreateRootSignature(provider, desc));
    if (!root)
      return false;
    const void *shaders[] = {native_smaa_edges, native_smaa_weights,
                             native_smaa_blend};
    size_t sizes[] = {sizeof(native_smaa_edges), sizeof(native_smaa_weights),
                      sizeof(native_smaa_blend)};
    for (int i = 0; i < 3; ++i) {
      pipelines[i].Attach(rex::ui::d3d12::util::CreateComputePipeline(
          device, shaders[i], sizes[i], root.Get()));
      if (!pipelines[i])
        return false;
    }
    return Lookup(device, area, uploads[0], AREATEX_WIDTH, AREATEX_HEIGHT, 2,
                  DXGI_FORMAT_R8G8_UNORM, areaTexBytes) &&
           Lookup(device, search, uploads[1], SEARCHTEX_WIDTH, SEARCHTEX_HEIGHT,
                  1, DXGI_FORMAT_R8_UNORM, searchTexBytes);
  }
  static bool Texture(ID3D12Device *device,
                      Microsoft::WRL::ComPtr<ID3D12Resource> &texture,
                      uint32_t w, uint32_t h, DXGI_FORMAT format, bool uav) {
    D3D12_RESOURCE_DESC d{};
    d.Dimension = D3D12_RESOURCE_DIMENSION_TEXTURE2D;
    d.Width = w;
    d.Height = h;
    d.DepthOrArraySize = d.MipLevels = 1;
    d.Format = format;
    d.SampleDesc.Count = 1;
    d.Flags = uav ? D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS
                  : D3D12_RESOURCE_FLAG_NONE;
    return SUCCEEDED(device->CreateCommittedResource(
        &rex::ui::d3d12::util::kHeapPropertiesDefault, D3D12_HEAP_FLAG_NONE, &d,
        uav ? D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE
            : D3D12_RESOURCE_STATE_COPY_DEST,
        nullptr, IID_PPV_ARGS(&texture)));
  }
  static bool Lookup(ID3D12Device *device,
                     Microsoft::WRL::ComPtr<ID3D12Resource> &texture,
                     Microsoft::WRL::ComPtr<ID3D12Resource> &upload, uint32_t w,
                     uint32_t h, uint32_t bytes, DXGI_FORMAT format,
                     const unsigned char *data) {
    if (!Texture(device, texture, w, h, format, false))
      return false;
    uint32_t pitch = (w * bytes + 255) & ~255u;
    D3D12_RESOURCE_DESC d{};
    d.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER;
    d.Width = uint64_t(pitch) * h;
    d.Height = d.DepthOrArraySize = d.MipLevels = 1;
    d.SampleDesc.Count = 1;
    d.Layout = D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
    D3D12_HEAP_PROPERTIES heap{};
    heap.Type = D3D12_HEAP_TYPE_UPLOAD;
    if (FAILED(device->CreateCommittedResource(
            &heap, D3D12_HEAP_FLAG_NONE, &d, D3D12_RESOURCE_STATE_GENERIC_READ,
            nullptr, IID_PPV_ARGS(&upload))))
      return false;
    uint8_t *mapped = nullptr;
    D3D12_RANGE empty{};
    if (FAILED(upload->Map(0, &empty, reinterpret_cast<void **>(&mapped))))
      return false;
    for (uint32_t y = 0; y < h; ++y)
      std::memcpy(mapped + y * pitch, data + y * w * bytes, w * bytes);
    upload->Unmap(0, nullptr);
    return true;
  }
};
thread_local std::unique_ptr<NativeSmaaResources> native_smaa;
} // namespace
