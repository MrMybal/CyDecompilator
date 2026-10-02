cbuffer Params : register(b1) { float4 Weights[8]; row_major float3x4 Bones; uint Count; float Bias; };
Texture2DArray<float4> Layers : register(t0);
TextureCube<float4> Sky : register(t1);
Texture2D<float> Shadow : register(t2);
ByteAddressBuffer Raw : register(t3);
Buffer<float4> Typed : register(t4);
RWByteAddressBuffer OutRaw : register(u0);
SamplerState S : register(s0);
SamplerComparisonState Cmp : register(s1);
static const float Kernel[5] = { 0.1, 0.2, 0.4, 0.2, 0.1 };

float4 PSStress(float4 pos : SV_Position, float3 uvw : TEXCOORD0, float3 dir : TEXCOORD1, nointerpolation uint layer : LAYER) : SV_Target
{
    float4 acc = 0;
    for (uint i = 0; i < Count; i++)
    {
        float4 w = Weights[i & 7];
        for (int k = 0; k < 5; k++)
            acc += Layers.SampleLevel(S, float3(uvw.xy + k * 0.01, layer), Bias) * Kernel[k] * w;
        if (acc.w > 4.0) break;
    }
    float sh = Shadow.SampleCmpLevelZero(Cmp, uvw.xy, uvw.z);
    float3 sky = Sky.Sample(S, normalize(dir)).rgb;
    uint word = Raw.Load(layer * 4);
    float4 t = Typed.Load(layer) + Layers.Load(int4(pos.xy, layer, 0));
    float3 skinned = mul(Bones, float4(dir, 1));
    half h = (half)acc.x * (half)0.5;
    float wave = WaveActiveSum(acc.y);
    if (WaveIsFirstLane()) OutRaw.Store(layer * 4, asuint(wave));
    return float4(sky * sh + skinned * h + t.rgb, asfloat(word) + acc.w);
}
