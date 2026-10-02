#version 450
layout(location = 0) in vec3 inNormal;
layout(location = 1) in vec2 inUV;
layout(location = 0) out vec4 outColor;
layout(set = 0, binding = 0) uniform PerFrame { mat4 viewProj; vec3 lightDir; float time; vec4 tint; } frame;
layout(set = 0, binding = 1) uniform sampler2D albedo;
layout(push_constant) uniform Push { float exposure; int mode; } pc;

vec3 tonemap(vec3 c) { return c / (c + vec3(1.0)); }

void main() {
    vec4 base = texture(albedo, inUV);
    float ndl = max(dot(normalize(inNormal), -frame.lightDir), 0.0);
    vec3 color = base.rgb * frame.tint.rgb * ndl * pc.exposure;
    if (pc.mode == 1) {
        color = tonemap(color);
    } else if (pc.mode == 2) {
        color = vec3(dot(color, vec3(0.299, 0.587, 0.114)));
    }
    for (int i = 0; i < 3; ++i) {
        color *= 0.9;
        if (color.r < 0.01) break;
    }
    if (base.a < 0.05) discard;
    outColor = vec4(color, base.a);
}
