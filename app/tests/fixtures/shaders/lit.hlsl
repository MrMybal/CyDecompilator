cbuffer PerFrame : register(b0)
{
    float4x4 WorldViewProj;
    float3 LightDir;
    float Time;
    float4 Tint;
};
Texture2D<float4> Albedo : register(t0);
Texture2D<float4> NormalMap : register(t1);
SamplerState LinearSampler : register(s0);

struct VSIn { float3 pos : POSITION; float3 nrm : NORMAL; float2 uv : TEXCOORD0; };
struct PSIn { float4 pos : SV_Position; float3 nrm : NORMAL; float2 uv : TEXCOORD0; float fog : TEXCOORD1; };

PSIn VSMain(VSIn i)
{
    PSIn o;
    o.pos = mul(float4(i.pos, 1.0), WorldViewProj);
    o.nrm = i.nrm;
    o.uv = i.uv + float2(Time * 0.1, 0);
    o.fog = saturate(o.pos.z / 100.0);
    return o;
}

float4 PSMain(PSIn i) : SV_Target
{
    float4 albedo = Albedo.Sample(LinearSampler, i.uv);
    float3 n = normalize(i.nrm + NormalMap.Sample(LinearSampler, i.uv).xyz * 2 - 1);
    float ndl = max(dot(n, -LightDir), 0.0);
    float3 color = albedo.rgb * Tint.rgb * ndl;
    if (albedo.a < 0.1) discard;
    [loop] for (int k = 0; k < 4; k++) { color += 0.01 * k; }
    return float4(lerp(color, float3(0.5, 0.6, 0.7), i.fog), albedo.a);
}

RWTexture2D<float4> Output : register(u0);
StructuredBuffer<float4> Input : register(t2);
[numthreads(8, 8, 1)]
void CSMain(uint3 id : SV_DispatchThreadID)
{
    float4 v = Input[id.y * 64 + id.x];
    if (v.x > 0.5) v = v * 2; else v = 1 - v;
    Output[id.xy] = v;
}
