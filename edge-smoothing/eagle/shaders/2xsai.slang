#version 450

layout(push_constant) uniform Push
{
    vec4 OutputSize;
    vec4 OriginalSize;
    vec4 SourceSize;
} params;

layout(std140, set = 0, binding = 0) uniform UBO
{
    mat4 MVP;
} global;


const vec3 dt = vec3(65536.0,256.0,1.0);


float GET_RESULT(float A, float B, float C, float D)
{
    return (sign(abs(A-C)+abs(A-D)) - sign(abs(B-C)+abs(B-D))); 
}


float reduce(vec3 color)
{ 
    return dot(color,dt);
}


#pragma stage vertex
layout(location = 0) in  vec4 Position;
layout(location = 1) in  vec2 TexCoord;
layout(location = 0) out vec2 vTexCoord;

/* Default Vertex shader */
void main()
{
    gl_Position = global.MVP * Position;
    vTexCoord   = TexCoord * 1.0001;
}

#pragma stage fragment
layout(location = 0) in  vec2 vTexCoord;
layout(location = 0) out vec4 FragColor;
layout(set = 0, binding = 2) uniform sampler2D Source;


void main()
{
    vec2 OGL2Size    = params.SourceSize.xy;
    vec2 OGL2InvSize = params.SourceSize.zw;

    // Calculating texel coordinates

    vec2 OGL2Pos = vTexCoord.xy*OGL2Size.xy;
    vec2 fp = fract(OGL2Pos);
    vec2 g1 = vec2( OGL2InvSize.x,OGL2InvSize.y);
    vec2 g2 = vec2(-OGL2InvSize.x,OGL2InvSize.y);


    if ((fp.x >= 0.50) && (fp.y < 0.50)) g2*=-1.0;

    vec2 pC4 = floor(OGL2Pos)/OGL2Size.xy + 0.5*OGL2InvSize;

    vec2 pC8 = pC4 + g1;
    vec2 pC0 = pC4 - g1;

    vec2 p04 = pC4 - 0.5*g1;
    vec2 pC3 = p04 + 0.5*g2;
    vec2 pC1 = pC3 - g2;
    vec2 pC5 = pC1 + g1;
    vec2 pC7 = pC3 + g1;


    // Reading the texels

    vec3 C0 = texture(Source,pC0   ).xyz; 
    vec3 C1 = texture(Source,pC1   ).xyz;
    vec3 C2 = texture(Source,pC4-g2).xyz;
    vec3 C3 = texture(Source,pC3   ).xyz;
    vec3 C4 = texture(Source,pC4   ).xyz;
    vec3 C5 = texture(Source,pC5   ).xyz;
    vec3 D4 = texture(Source,pC8-g2).xyz;
    vec3 C6 = texture(Source,pC4+g2).xyz;
    vec3 C7 = texture(Source,pC7   ).xyz;
    vec3 C8 = texture(Source,pC8   ).xyz;
    vec3 D5 = texture(Source,pC5+g1).xyz;
    vec3 D0 = texture(Source,pC7+g2).xyz;
    vec3 D1 = texture(Source,pC8+g2).xyz;
    vec3 D2 = texture(Source,pC7+g1).xyz;
    vec3 p10,p11;

    float c0 = reduce(C0);float c1 = reduce(C1);
    float c2 = reduce(C2);float c3 = reduce(C3);
    float c4 = reduce(C4);float c5 = reduce(C5);
    float c6 = reduce(C6);float c7 = reduce(C7);
    float c8 = reduce(C8);float d0 = reduce(D0);
    float d1 = reduce(D1);float d2 = reduce(D2);
    float d4 = reduce(D4);float d5 = reduce(D5);


    /*                2xSaI code                  */
    /*  Copied from the Dosbox source code        */
    /*  Copyright (C) 2002-2007  The DOSBox Team  */
    /*  License: GNU-GPL                          */
    /*  Adapted by guest(r) on 20.4 and 9.5. 2007 */

    if (c4 == c8) {
        if (c5 != c7) {
            if (((c4 == c3)&&(c7 == d2))||((c4 == c5)&&(c4 == c6)&&(c3 != c7)&&(c7 == d0))) {
                    p10 = C4;
            } else {
                    p10 = 0.5*(C4+C7);
            }
            p11 = C4;
        } else {
            if (c4 == c5) {
                    p10 = C4;
                    p11 = C4;
            } else {
                float r;
                r  = GET_RESULT(c4,c5,c3,c1);
                r -= GET_RESULT(c5,c4,d4,c2);
                r -= GET_RESULT(c5,c4,c6,d1);
                r += GET_RESULT(c4,c5,d5,d2);
                if (r > 0.0) p11 = C4;
                else if (r < 0.0) p11 = C5;
                else p11 = 0.25*(C4+C5+C7+C8);
                p10 = 0.5*(C4+C7);
            }
        }
    } else
        if (c5 == c7) {
            if (((c7 == c6)&&(c4 == c2))||((c7 == c3)&&(c7 == c8)&&(c4 != c6)&&(c4 == c0))) {
                    p10 = C7;
            } else {
                    p10 = 0.5*(C4+C7);
            }
            p11 = C5;
        } else {
            p11 = 0.25*(C4+C5+C7+C8);

            if ((c4 == c5)&&(c4 == c6)&&(c3 != c7)&&(c7 == d0)) {
                    p10 = C4;
            } else if ((c7 == c3)&&(c7 == c8)&&(c4 != c6)&&(c4 == c0)) {
                       p10 = C7;
            } else {
                p10 = 0.5*(C4+C7);
        } 
    }

    // Distributing the final products 

    vec3 color; 
    
    if (fp.x >= 0.5 && fp.y >= 0.5) color = p11; else
    if (fp.x <  0.5 && fp.y <  0.5) color =  C4; else color = p10; 


    FragColor = vec4(color, 1.0);
}
