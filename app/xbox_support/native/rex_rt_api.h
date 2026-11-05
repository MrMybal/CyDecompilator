#pragma once
#include <atomic>
#include <cstdint>
struct NativeRtStatus {
  int32_t state; // 0 off, 1 waiting, 2 active, -1 unsupported, -2 init failed,
                 // -3 capture failed
  uint32_t draws;
  uint64_t frames;
};
using NativeRtSetProjection = void (*)(float, float);
inline std::atomic<NativeRtSetProjection> native_rt_projection{nullptr};
inline void XboxNativeRtProjection(float fov, float aspect) {
  if (auto publish = native_rt_projection.load())
    publish(fov, aspect);
}
