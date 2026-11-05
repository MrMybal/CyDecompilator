// Capture real post-VS triangles, before clipping, into a view-space BLAS.
// Undo the translator's guest->host NDC conversion. Clip W is view depth for
// Halo's perspective scene passes. No depth-image reconstruction is involved.
cbuffer Capture : register(b15, space15) {
  float4 ndc_scale; // xyz scale; w tangent(vertical FOV/2)
  float4 ndc_offset; // xyz offset; w projection aspect
};
#ifndef NATIVE_RT_INTERPOLATORS
#define NATIVE_RT_INTERPOLATORS 0
#endif
struct Input {
#if NATIVE_RT_INTERPOLATORS > 0
  float4 interpolators[NATIVE_RT_INTERPOLATORS] : TEXCOORD0;
#endif
  float4 position : SV_Position;
};
struct Output {
#if NATIVE_RT_INTERPOLATORS > 0
  float4 interpolators[NATIVE_RT_INTERPOLATORS] : TEXCOORD0;
#endif
  float4 position : SV_Position;
  float4 view : TEXCOORD16;
  float clip_z : TEXCOORD17;
};
[maxvertexcount(3)]
void main(triangle Input vertices[3], uint primitive : SV_PrimitiveID,
          inout TriangleStream<Output> stream) {
  bool valid = all(isfinite(vertices[0].position)) &&
               all(isfinite(vertices[1].position)) &&
               all(isfinite(vertices[2].position)) &&
               all(isfinite(ndc_scale)) && all(abs(ndc_scale.xy) > 0.000001) &&
               max(vertices[0].position.w,max(vertices[1].position.w,vertices[2].position.w)) > 0.02 &&
               !(vertices[0].position.w == 1 && vertices[1].position.w == 1 && vertices[2].position.w == 1);
  if (!valid) return;
  [unroll] for (uint i = 0; i < 3; ++i) {
    float4 p = vertices[i].position;
    Output o;
    // A unique material tile per triangle. Running the ORIGINAL pixel shader
    // here preserves texture sampling, discard/alpha test and HDR radiance.
    uint tile = uint(ndc_scale.z) + primitive;
    float2 corner = i == 0 ? float2(0,0) : (i == 1 ? float2(1,0) : float2(0,1));
    float2 pixel = float2(tile % 256, tile / 256) * 16 + corner * 16;
    o.position = float4(pixel / float2(4096,8192) * float2(2,-2) + float2(-1,1), 0, 1);
#ifdef NATIVE_RT_SURFACE
    o.position = p;
#endif
#if NATIVE_RT_INTERPOLATORS > 0
    [unroll] for (uint t=0; t<NATIVE_RT_INTERPOLATORS; ++t)
      o.interpolators[t] = vertices[i].interpolators[t];
#endif
    float2 clip = (p.xy - ndc_offset.xy * p.w) / ndc_scale.xy;
    o.view = float4(clip.x * ndc_scale.w * ndc_offset.w,
                    clip.y * ndc_scale.w, p.w,
                    float(tile | (uint(ndc_offset.z) << 20)));
    o.clip_z = p.z;
    stream.Append(o);
  }
  stream.RestartStrip();
}
