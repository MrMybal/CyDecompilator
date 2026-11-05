// SMAA 1x, three compute passes. The reference algorithm and lookup tables
// are in third_party/smaa, with the authors' MIT license retained.
cbuffer Metrics : register(b0) { float4 rt_metrics; }
#define SMAA_RT_METRICS rt_metrics
#define SMAA_PRESET_HIGH
#define SMAA_HLSL_4
#include "SMAA.compute.hlsl"
Texture2D color_texture : register(t0);
Texture2D edge_texture : register(t1);
Texture2D weight_texture : register(t2);
Texture2D area_texture : register(t3);
Texture2D search_texture : register(t4);
RWTexture2D<float4> destination : register(u0);

[numthreads(16, 8, 1)] void edges(uint3 pixel : SV_DispatchThreadID) {
  if (any(pixel.xy >= uint2(rt_metrics.zw)))
    return;
  float2 uv = (float2(pixel.xy) + .5) * rt_metrics.xy;
  float4 offsets[3] = {float4(0,0,0,0),float4(0,0,0,0),float4(0,0,0,0)};
  SMAAEdgeDetectionVS(uv, offsets);
  destination[pixel.xy] =
      float4(SMAAColorEdgeDetectionPS(uv, offsets, color_texture), 0, 0);
}

[numthreads(16, 8, 1)] void weights(uint3 pixel : SV_DispatchThreadID) {
  if (any(pixel.xy >= uint2(rt_metrics.zw)))
    return;
  float2 uv = (float2(pixel.xy) + .5) * rt_metrics.xy, pixcoord;
  float4 offsets[3];
  SMAABlendingWeightCalculationVS(uv, pixcoord, offsets);
  destination[pixel.xy] = SMAABlendingWeightCalculationPS(
      uv, pixcoord, offsets, edge_texture, area_texture, search_texture, 0);
}
[numthreads(16, 8, 1)] void blend(uint3 pixel : SV_DispatchThreadID) {
  if (any(pixel.xy >= uint2(rt_metrics.zw)))
    return;
  float2 uv = (float2(pixel.xy) + .5) * rt_metrics.xy;
  float4 offset;
  SMAANeighborhoodBlendingVS(uv, offset);
  destination[pixel.xy] =
      SMAANeighborhoodBlendingPS(uv, offset, color_texture, weight_texture);
}
