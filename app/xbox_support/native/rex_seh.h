// ReXGlue 0.10.0's generated PCH omits this header when SEH generation is enabled.
// Keep its native exception handling active in consumer projects.
#pragma once
#ifdef _WIN32
#include <windows.h>
#endif
#include <rex/platform/exceptions.h>
