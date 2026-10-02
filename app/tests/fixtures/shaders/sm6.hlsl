cbuffer Scene : register(b0)
{
    float4x4 ViewProj;
    float3 CameraPos;
    float Exposure;
    int LightCount;
    uint Mode;
    float2 Jitter;
};
struct Light { float3 position; float radius; float3 color; float intensity; };
StructuredBuffer<Light> Lights : register(t0);
Texture2D<float4> Albedo : register(t1);
SamplerState Linear : register(s0);
RWTexture2D<float4> Output : register(u0);
RWStructuredBuffer<uint> Counters : register(u1);
groupshared float Shared[64];

struct PSIn { float4 pos : SV_Position; float3 world : POSITION; float3 normal : NORMAL; float2 uv : TEXCOORD0; };

float4 PSMain(PSIn i) : SV_Target
{
    float4 base = Albedo.Sample(Linear, i.uv + Jitter);
    float3 n = normalize(i.normal);
    float3 lit = 0;
    for (int k = 0; k < LightCount; k++)
    {
        Light L = Lights[k];
        float3 d = L.position - i.world;
        float dist = length(d);
        if (dist > L.radius) continue;
        float ndl = saturate(dot(n, d / dist));
        lit += L.color * L.intensity * ndl / (1.0 + dist * dist);
    }
    float3 color;
    switch (Mode)
    {
        case 0: color = base.rgb * lit; break;
        case 1: color = lit; break;
        default: color = n * 0.5 + 0.5; break;
    }
    if (base.a < 0.01) discard;
    return float4(color * Exposure, base.a);
}

struct VSIn { float3 pos : POSITION; float3 normal : NORMAL; float2 uv : TEXCOORD0; };
PSIn VSMain(VSIn v)
{
    PSIn o;
    o.world = v.pos;
    o.pos = mul(float4(v.pos, 1.0), ViewProj);
    o.normal = v.normal;
    o.uv = v.uv * 2.0;
    return o;
}

[numthreads(64, 1, 1)]
void CSMain(uint3 id : SV_DispatchThreadID, uint gi : SV_GroupIndex)
{
    float4 c = Output[id.xy];
    Shared[gi] = dot(c.rgb, float3(0.299, 0.587, 0.114));
    GroupMemoryBarrierWithGroupSync();
    float sum = 0;
    for (uint j = 0; j < 64; j += 8) sum += Shared[j];
    if (sum > 1.0) InterlockedAdd(Counters[0], 1);
    Output[id.xy] = float4(c.rgb * (sum / 8.0), c.a);
}
