// Two edge-aware spatial passes on RT illumination, never on raster detail.
Texture2D<float4> source_colour : register(t2);
Texture2D<float4> raw_effect : register(t4);
Texture2D<float4> guide_image : register(t5);
Texture2D<float4> filtered_effect : register(t6);
RWTexture2D<float4> destination : register(u0);
RWTexture2D<float4> temporary : register(u3);
cbuffer Parameters : register(b0) {
  uint width,height; float tangent_fov,aspect;
  float strength,radius; uint pass_index,debug_view;
  uint effects; float reflections,indirect,roughness;
};
[numthreads(8,8,1)]
void main(uint3 id : SV_DispatchThreadID) {
  if(id.x>=width || id.y>=height) return;
  float4 guide=guide_image[id.xy];
  float4 original=source_colour[id.xy];
  if(debug_view) {
    if(pass_index==0) temporary[id.xy]=raw_effect[id.xy];
    else destination[id.xy]=guide.w>0 ? float4(raw_effect[id.xy].rgb,original.a) : original;
    return;
  }
  float4 value=float4(0,0,0,1);
  if(guide.w>0) {
    float4 sum=0; float weights=0;
    [unroll] for(int y=-2;y<=2;++y) [unroll] for(int x=-2;x<=2;++x) {
      int2 pixel=clamp(int2(id.xy)+int2(x,y)*(pass_index==0 ? 1 : 2),int2(0,0),int2(width-1,height-1));
      float4 other=guide_image[pixel];
      if(other.w<=0) continue;
      float depth_error=abs(other.w-guide.w)/max(.015,guide.w*.003);
      float weight=exp(-.5*(x*x+y*y)-depth_error)*pow(saturate(dot(guide.xyz,other.xyz)),32);
      sum+=(pass_index==0 ? raw_effect[pixel] : filtered_effect[pixel])*weight;
      weights+=weight;
    }
    value=sum/max(weights,.00001);
  }
  if(pass_index==0) temporary[id.xy]=value;
  else {
    // Preserve bright/emissive pixels. The source is already shaded by Halo.
    float luminance=dot(original.rgb,float3(.2126,.7152,.0722));
    float preserve=smoothstep(.55,.95,luminance);
    float ao=lerp(value.a,1,preserve);
    destination[id.xy]=float4(original.rgb*ao+value.rgb,original.a);
  }
}
