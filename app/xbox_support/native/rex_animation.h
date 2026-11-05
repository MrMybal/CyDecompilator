#pragma once
#include <array>
#include <cstdint>
#include <vector>
struct PPCContext;
// Interpolate render copies for Saber and the classic renderer. Simulation
// memory stays authoritative. The root export reports a changed transform when
// the interpolated copy changes, so Saber uploads it between simulation ticks.
struct XboxNativePoseExport {
  PPCContext &ctx;
  uint8_t *base;
  uint32_t object, output;
  bool root, classic;
  XboxNativePoseExport(PPCContext &, uint8_t *, bool root_matrix,
                       bool classic_path = false);
  ~XboxNativePoseExport();
};
void XboxNativeAnimationSelfTest();
void XboxNativeAnimationResetTrace();
bool XboxNativeCinematicActive(uint8_t *base);
// Cinematic and seated-vehicle render cameras. The window builder leaves
// observer/simulation data intact; on-foot mouse aiming bypasses this hook.
struct XboxNativeCinematicCamera {
  uint8_t *base;
  uint32_t window;
  XboxNativeCinematicCamera(PPCContext &, uint8_t *);
  ~XboxNativeCinematicCamera();
};
void XboxNativeAnimationIntegrationCheck(uint8_t *base, uint32_t arena);
struct XboxNativeFirstPersonPose {
  uint8_t *base;
  uint32_t source = 0;
  uint32_t output = 0, count = 0;
  std::array<float, 3> sprint_offset{};
  std::vector<uint8_t> original;
  XboxNativeFirstPersonPose(PPCContext &, uint8_t *);
  ~XboxNativeFirstPersonPose();
};
// Each classic draw owns guest-addressable scratch above its original stack
// frame. Only the two render callers of object_get_node_matrices receive it.
struct XboxNativeClassicDraw {
  PPCContext &ctx;
  uint32_t stack, scratch;
  XboxNativeClassicDraw *parent;
  explicit XboxNativeClassicDraw(PPCContext &);
  ~XboxNativeClassicDraw();
};
struct XboxNativeClassicNodes {
  PPCContext &ctx;
  uint8_t *base;
  uint32_t object;
  uint64_t caller;
  XboxNativeClassicNodes(PPCContext &, uint8_t *);
  ~XboxNativeClassicNodes();
};
