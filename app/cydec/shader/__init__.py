"""CyDecompilator's own shader engine: DXBC (SM4/SM5), DXIL container (SM6) and SPIR-V.

Nothing here comes from another decompiler: the container formats and token encodings are
read from the public specifications (d3d11tokenizedprogramformat.hpp, the DXBC container
layout and the Khronos SPIR-V specification) and turned into HLSL/GLSL-like source.
"""
