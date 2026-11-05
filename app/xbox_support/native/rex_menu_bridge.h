#pragma once
#include <cstdint>
#include <string_view>
struct PPCContext;
// GFx 3 mouse types verified in this game's HandleEvent dispatch:
// 1 move, 2 down, 3 up, 4 wheel. Positions are client physical pixels.
void XboxNativeMenuMouse(uint32_t type, float x, float y, uint32_t width,
                         uint32_t height, uint32_t button = 0, float wheel = 0);
void XboxNativeMenuEnabled(bool enabled);
void XboxNativeGfxAdvance(PPCContext &, uint8_t *base);
// Relative pixels are consumed once by Halo's player-control update, after
// the controller response curve. No stick dead zone or frame-time scaling.
void XboxNativeMouseMotion(float dx, float dy);
void XboxNativeMouseReset();
void XboxNativeSprintHeld(bool held);
bool XboxNativeSprintIsHeld();
bool XboxNativeSprintActive();
bool XboxNativeRequestSkip();
void XboxNativeSkipTick(PPCContext &, uint8_t *base);
bool XboxNativeQueueMap(std::string_view map);
uint16_t XboxNativeBootButtons();
void XboxNativeObserveCampaignLaunch(PPCContext &, uint8_t *base);
void XboxNativeSaberMapArgument(PPCContext &, uint8_t *base);
void XboxNativeDirectMapTick(PPCContext &, uint8_t *base);
struct XboxNativeMapAdvance {
  PPCContext &ctx;
  uint8_t *base;
  ~XboxNativeMapAdvance() { XboxNativeDirectMapTick(ctx, base); }
};
void XboxNativeSprintSpeed(PPCContext &, uint8_t *base);
void XboxNativePlayerLook(PPCContext &, uint8_t *base);
void XboxNativeSleepProbe(PPCContext &, uint8_t *base);
void XboxNativeFramePacing(PPCContext &);
void XboxNativeGfxProcessMouse(PPCContext &, uint8_t *base);
bool XboxNativeMenuOwnsMouse(PPCContext &, uint8_t *base);
bool XboxNativeIgnoreGuestMouse(PPCContext &, uint8_t *base);
void XboxNativeVideoPolicy(uint32_t object, uint8_t *base);
struct XboxNativeVideoSettingsGuard {
  uint32_t object;
  uint8_t *base;
  ~XboxNativeVideoSettingsGuard() { XboxNativeVideoPolicy(object, base); }
};
