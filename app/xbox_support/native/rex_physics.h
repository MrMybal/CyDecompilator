#pragma once
#include <cstdint>
struct PPCContext;
bool XboxNativeBipedSubsteps(PPCContext &, uint8_t *);
void XboxNativeBipedForce(PPCContext &);
uint64_t XboxNativePhysicsStepCount();
