// Native DXR over captured triangles and original-pixel-shader material tiles.
RaytracingAccelerationStructure scene : register(t0);
ByteAddressBuffer vertices : register(t1);
Texture2D<float4> source_colour : register(t2);
Texture2D<float4> materials : register(t3);
Texture2D<float> raster_depth : register(t7);
RWTexture2D<float4> effect_image : register(u1);
RWTexture2D<float4> guide_image : register(u2);
cbuffer Parameters : register(b0) {
  uint width, height;
  float tangent_fov, aspect;
  float strength, radius;
  uint rays, debug_view;
  uint effects;
  float reflection_strength, gi_strength, roughness;
  float4 viewport;
  float depth_min,depth_scale;
  float reversed_depth,padding;
};
float3 vertex(uint index) { return asfloat(vertices.Load3(index * 20)); }
uint metadata(uint primitive) { return uint(asfloat(vertices.Load(primitive * 60 + 12))); }
float projected_depth(uint primitive,float2 bary) {
  float3 weights=float3(1-bary.x-bary.y,bary);
  uint first=primitive*60;
  float3 z=asfloat(uint3(vertices.Load(first+16),vertices.Load(first+36),vertices.Load(first+56)));
  float3 w=float3(vertex(primitive*3).z,vertex(primitive*3+1).z,vertex(primitive*3+2).z);
  return dot(z,weights)/dot(w,weights)*depth_scale+depth_min;
}
float4 material(uint primitive, float2 bary) {
  uint tile = metadata(primitive) & 0xFFFFF;
  uint2 local = min(uint2(saturate(bary) * 16),14);
  // The diagonal uses the top-left rasterization rule. Stay inside the tile.
  if (local.x + local.y > 14) local.y = 14 - local.x;
  return materials[uint2(tile % 256,tile / 256)*16 + local];
}
float random(uint seed) {
  seed ^= seed >> 16; seed *= 0x7feb352d; seed ^= seed >> 15;
  seed *= 0x846ca68b; seed ^= seed >> 16;
  return float(seed & 0xFFFFFF) / 16777216.;
}
struct Hit { float t; uint primitive; float2 bary; float3 colour; uint flags; };
bool TraceSurface(RayDesc ray, uint seed, uint purpose, out Hit hit) {
  RayQuery<RAY_FLAG_NONE> q;
  q.TraceRayInline(scene,RAY_FLAG_NONE,0xFF,ray);
  while(q.Proceed()) {
    if(q.CandidateType() != CANDIDATE_NON_OPAQUE_TRIANGLE) continue;
    uint primitive = q.CandidatePrimitiveIndex();
    uint flags = metadata(primitive) >> 20;
    float2 bary=q.CandidateTriangleBarycentrics();
    float4 surface = material(primitive,bary);
    float3 position=ray.Origin+ray.Direction*q.CandidateTriangleRayT();
    float2 screen=float2(position.x/(position.z*tangent_fov*aspect),-position.y/(position.z*tangent_fov))*.5+.5;
    bool visible_coverage=false;
    if(position.z>.02 && all(screen>0) && all(screen<1)) {
      uint2 pixel=uint2(viewport.xy+screen*viewport.zw);
      float real_depth=raster_depth[pixel];
      float candidate_depth=projected_depth(primitive,bary);
      visible_coverage=abs(real_depth-candidate_depth)<.00005;
      // Primary visibility is authoritative at raster resolution, including
      // alpha discard and the real depth ordering of the original shaders.
      if(purpose==0 && !visible_coverage) continue;
      bool uncovered=reversed_depth>0 ? real_depth<candidate_depth-.00005 : real_depth>candidate_depth+.00005;
      if((flags&16) && uncovered) continue;
    } else if(purpose==0) continue;
    // A discarded pixel is left at the sentinel, regardless of output alpha.
    if(purpose!=0 && !visible_coverage && (surface.r < -65000 || !all(isfinite(surface)))) continue;
    // Blended/additive layers remain in the raster image. They do not turn
    // into opaque primary surfaces or shadow blockers for emissive overlays.
    if(purpose == 0 && (flags & 1)) continue;
    if(purpose == 1 && (flags & 2)) continue;
    float opacity = (flags & 1) ? saturate(surface.a) : 1;
    if((flags & 2) && purpose == 2) opacity = 1;
    if(opacity <= random(seed ^ (primitive*1664525u))) continue;
    q.CommitNonOpaqueTriangleHit();
  }
  if(q.CommittedStatus() != COMMITTED_TRIANGLE_HIT) { hit=(Hit)0; return false; }
  hit.t=q.CommittedRayT(); hit.primitive=q.CommittedPrimitiveIndex();
  hit.bary=q.CommittedTriangleBarycentrics();
  hit.colour=max(material(hit.primitive,hit.bary).rgb,0);
  hit.flags=metadata(hit.primitive)>>20;
  float alpha=saturate(material(hit.primitive,hit.bary).a);
  if(hit.flags&4) hit.colour/=max(alpha,.01);
  if(hit.flags&8) hit.colour*=alpha;
  return true;
}
[numthreads(8,8,1)]
void main(uint3 id : SV_DispatchThreadID) {
  if(id.x>=width || id.y>=height) return;
  effect_image[id.xy]=float4(0,0,0,1);
  guide_image[id.xy]=0;
  float2 uv=(float2(id.xy)+.5)/float2(width,height);
  float3 direction=normalize(float3((uv.x*2-1)*tangent_fov*aspect,(1-uv.y*2)*tangent_fov,1));
  RayDesc primary={float3(0,0,0),.02,direction,4096};
  uint seed=id.x+id.y*width;
  Hit surface;
  if(!TraceSurface(primary,seed,0,surface)) return;
  uint v=surface.primitive*3;
  float3 a=vertex(v),b=vertex(v+1),c=vertex(v+2);
  float3 normal=normalize(cross(b-a,c-a));
  if(!all(isfinite(normal))) return;
  if(dot(normal,direction)>0) normal=-normal;
  float3 position=direction*surface.t;
  guide_image[id.xy]=float4(normal,position.z);
  if(debug_view) { effect_image[id.xy]=float4(normal*.5+.5,0); return; }
  float3 axis=abs(normal.z)<.9 ? float3(0,0,1) : float3(0,1,0);
  float3 tangent=normalize(cross(axis,normal)),bitangent=cross(normal,tangent);
  float rotation=random(seed)*6.2831853;
  float blocked=0;
  float3 indirect=0;
  // Relative offset avoids a dense mesh self-shadowing at large view distances.
  float bias=max(.008,position.z*.00015);
  if(effects&5) [loop] for(uint i=0;i<rays;++i) {
    float r=sqrt((i+.5)/float(rays)),angle=i*2.39996323+rotation;
    float3 d=tangent*cos(angle)*r+bitangent*sin(angle)*r+normal*sqrt(1-r*r);
    RayDesc secondary={position+normal*bias,bias,d,radius};
    Hit bounce;
    if(TraceSurface(secondary,seed+i*7919,1,bounce))
      blocked+=1-saturate(bounce.t/radius);
    if((effects&4) && TraceSurface(secondary,seed+i*7919,2,bounce))
      indirect+=min(bounce.colour,8);
  }
  // This remains a hybrid pass: the base image already contains baked light.
  // Bound AO to avoid multiplying that image down to black.
  float visibility=(effects&1) ? 1-strength*.28*blocked/max(float(rays),1) : 1;
  float3 addition=indirect*(gi_strength/max(float(rays),1))*.2;
  if(effects&2) {
    float3 reflected=reflect(direction,normal);
    float3 radiance=0;
    [unroll] for(uint i=0;i<4;++i) {
      float angle=rotation+i*2.39996323;
      float3 d=normalize(reflected+(tangent*cos(angle)+bitangent*sin(angle))*roughness*.25);
      RayDesc reflection={position+normal*bias,bias,d,128};
      Hit reflected_surface;
      if(TraceSurface(reflection,seed+i*6151,2,reflected_surface))
        radiance+=min(reflected_surface.colour,8);
    }
    // No invented dark environment and no global glossy replacement material.
    float fresnel=.04+.96*pow(1-saturate(dot(normal,-direction)),5);
    addition+=radiance*.25*reflection_strength*fresnel;
  }
  effect_image[id.xy]=float4(addition,visibility);
}
