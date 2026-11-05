#pragma once
#include <cstdint>
#include <rex/ui/d3d12/d3d12_provider.h>
#include <rex/ui/d3d12/d3d12_util.h>
struct NativeRtDraw {
  ID3D12Device *device;
  ID3D12PipelineState *pipeline;
  ID3D12RootSignature *root;
  uint32_t count, indexed;
  float scale[3], offset[3];
  uint32_t triangles = 0, material_flags = 0;
  D3D12_VIEWPORT viewport{};
  D3D12_RECT scissor{};
};
struct NativeRtPresent {
  ID3D12Resource *output;
  D3D12_RESOURCE_STATES state;
};
bool NativeRtEnabled();
ID3D12RootSignature *NativeRtCreateRoot(const rex::ui::d3d12::D3D12Provider &,
                                        const D3D12_ROOT_SIGNATURE_DESC &);
void NativeRtRegisterPipeline(ID3D12Device *,
                              const D3D12_GRAPHICS_PIPELINE_STATE_DESC &,
                              ID3D12PipelineState *);
void NativeRtCapture(ID3D12GraphicsCommandList *, const void *);
void NativeRtRememberTargets(UINT, const D3D12_CPU_DESCRIPTOR_HANDLE *, BOOL,
                             const D3D12_CPU_DESCRIPTOR_HANDLE *);
void NativeRtComposite(ID3D12GraphicsCommandList *, const void *);
void NativeRtShutdown();
