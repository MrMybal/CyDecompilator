;
; Input signature:
;
; Name                 Index   Mask Register SysValue  Format   Used
; -------------------- ----- ------ -------- -------- ------- ------
; SV_Position              0   xyzw        0      POS   float       
; POSITION                 0   xyz         1     NONE   float   xyz 
; NORMAL                   0   xyz         2     NONE   float   xyz 
; TEXCOORD                 0   xy          3     NONE   float   xy  
;
;
; Output signature:
;
; Name                 Index   Mask Register SysValue  Format   Used
; -------------------- ----- ------ -------- -------- ------- ------
; SV_Target                0   xyzw        0   TARGET   float   xyzw
;
; shader hash: 16dabb92c32823e43203b7aa16611811
;
; Pipeline Runtime Information: 
;
; Pixel Shader
; DepthOutput=0
; SampleFrequency=0
;
;
; Input signature:
;
; Name                 Index             InterpMode DynIdx
; -------------------- ----- ---------------------- ------
; SV_Position              0          noperspective       
; POSITION                 0                 linear       
; NORMAL                   0                 linear       
; TEXCOORD                 0                 linear       
;
; Output signature:
;
; Name                 Index             InterpMode DynIdx
; -------------------- ----- ---------------------- ------
; SV_Target                0                              
;
; Buffer Definitions:
;
; cbuffer Scene
; {
;
;   struct hostlayout.Scene
;   {
;
;       column_major float4x4 ViewProj;               ; Offset:    0
;       float3 CameraPos;                             ; Offset:   64
;       float Exposure;                               ; Offset:   76
;       int LightCount;                               ; Offset:   80
;       uint Mode;                                    ; Offset:   84
;       float2 Jitter;                                ; Offset:   88
;   
;   } Scene;                                          ; Offset:    0 Size:    96
;
; }
;
; Resource bind info for Lights
; {
;
;   struct struct.Light
;   {
;
;       float3 position;                              ; Offset:    0
;       float radius;                                 ; Offset:   12
;       float3 color;                                 ; Offset:   16
;       float intensity;                              ; Offset:   28
;   
;   } $Element;                                       ; Offset:    0 Size:    32
;
; }
;
;
; Resource Bindings:
;
; Name                                 Type  Format         Dim      ID      HLSL Bind  Count
; ------------------------------ ---------- ------- ----------- ------- -------------- ------
; Scene                             cbuffer      NA          NA     CB0            cb0     1
; Linear                            sampler      NA          NA      S0             s0     1
; Lights                            texture  struct         r/o      T0             t0     1
; Albedo                            texture     f32          2d      T1             t1     1
;
;
; ViewId state:
;
; Number of inputs: 14, outputs: 4
; Outputs dependent on ViewId: {  }
; Inputs contributing to computation of Outputs:
;   output 0 depends on inputs: { 4, 5, 6, 8, 9, 10, 12, 13 }
;   output 1 depends on inputs: { 4, 5, 6, 8, 9, 10, 12, 13 }
;   output 2 depends on inputs: { 4, 5, 6, 8, 9, 10, 12, 13 }
;   output 3 depends on inputs: { 12, 13 }
;
target datalayout = "e-m:e-p:32:32-i1:32-i8:32-i16:32-i32:32-i64:64-f16:32-f32:32-f64:64-n8:16:32:64"
target triple = "dxil-ms-dx"

%dx.types.Handle = type { i8* }
%dx.types.CBufRet.f32 = type { float, float, float, float }
%dx.types.ResRet.f32 = type { float, float, float, float, i32 }
%dx.types.CBufRet.i32 = type { i32, i32, i32, i32 }
%"class.StructuredBuffer<Light>" = type { %struct.Light }
%struct.Light = type { <3 x float>, float, <3 x float>, float }
%"class.Texture2D<vector<float, 4> >" = type { <4 x float>, %"class.Texture2D<vector<float, 4> >::mips_type" }
%"class.Texture2D<vector<float, 4> >::mips_type" = type { i32 }
%hostlayout.Scene = type { [4 x <4 x float>], <3 x float>, float, i32, i32, <2 x float> }
%struct.SamplerState = type { i32 }

define void @PSMain() {
  %1 = call %dx.types.Handle @dx.op.createHandle(i32 57, i8 0, i32 1, i32 1, i1 false)  ; CreateHandle(resourceClass,rangeId,index,nonUniformIndex)
  %2 = call %dx.types.Handle @dx.op.createHandle(i32 57, i8 0, i32 0, i32 0, i1 false)  ; CreateHandle(resourceClass,rangeId,index,nonUniformIndex)
  %3 = call %dx.types.Handle @dx.op.createHandle(i32 57, i8 3, i32 0, i32 0, i1 false)  ; CreateHandle(resourceClass,rangeId,index,nonUniformIndex)
  %4 = call %dx.types.Handle @dx.op.createHandle(i32 57, i8 2, i32 0, i32 0, i1 false)  ; CreateHandle(resourceClass,rangeId,index,nonUniformIndex)
  %5 = call float @dx.op.loadInput.f32(i32 4, i32 3, i32 0, i8 0, i32 undef)  ; LoadInput(inputSigId,rowIndex,colIndex,gsVertexAxis)
  %6 = call float @dx.op.loadInput.f32(i32 4, i32 3, i32 0, i8 1, i32 undef)  ; LoadInput(inputSigId,rowIndex,colIndex,gsVertexAxis)
  %7 = call float @dx.op.loadInput.f32(i32 4, i32 2, i32 0, i8 0, i32 undef)  ; LoadInput(inputSigId,rowIndex,colIndex,gsVertexAxis)
  %8 = call float @dx.op.loadInput.f32(i32 4, i32 2, i32 0, i8 1, i32 undef)  ; LoadInput(inputSigId,rowIndex,colIndex,gsVertexAxis)
  %9 = call float @dx.op.loadInput.f32(i32 4, i32 2, i32 0, i8 2, i32 undef)  ; LoadInput(inputSigId,rowIndex,colIndex,gsVertexAxis)
  %10 = call float @dx.op.loadInput.f32(i32 4, i32 1, i32 0, i8 0, i32 undef)  ; LoadInput(inputSigId,rowIndex,colIndex,gsVertexAxis)
  %11 = call float @dx.op.loadInput.f32(i32 4, i32 1, i32 0, i8 1, i32 undef)  ; LoadInput(inputSigId,rowIndex,colIndex,gsVertexAxis)
  %12 = call float @dx.op.loadInput.f32(i32 4, i32 1, i32 0, i8 2, i32 undef)  ; LoadInput(inputSigId,rowIndex,colIndex,gsVertexAxis)
  %13 = call %dx.types.CBufRet.f32 @dx.op.cbufferLoadLegacy.f32(i32 59, %dx.types.Handle %4, i32 5)  ; CBufferLoadLegacy(handle,regIndex)
  %14 = extractvalue %dx.types.CBufRet.f32 %13, 2
  %15 = extractvalue %dx.types.CBufRet.f32 %13, 3
  %16 = fadd fast float %14, %5
  %17 = fadd fast float %15, %6
  %18 = call %dx.types.ResRet.f32 @dx.op.sample.f32(i32 60, %dx.types.Handle %1, %dx.types.Handle %3, float %16, float %17, float undef, float undef, i32 0, i32 0, i32 undef, float undef)  ; Sample(srv,sampler,coord0,coord1,coord2,coord3,offset0,offset1,offset2,clamp)
  %19 = extractvalue %dx.types.ResRet.f32 %18, 0
  %20 = extractvalue %dx.types.ResRet.f32 %18, 1
  %21 = extractvalue %dx.types.ResRet.f32 %18, 2
  %22 = extractvalue %dx.types.ResRet.f32 %18, 3
  %23 = call float @dx.op.dot3.f32(i32 55, float %7, float %8, float %9, float %7, float %8, float %9)  ; Dot3(ax,ay,az,bx,by,bz)
  %24 = call float @dx.op.unary.f32(i32 25, float %23)  ; Rsqrt(value)
  %25 = fmul fast float %24, %7
  %26 = fmul fast float %24, %8
  %27 = fmul fast float %24, %9
  %28 = call %dx.types.CBufRet.i32 @dx.op.cbufferLoadLegacy.i32(i32 59, %dx.types.Handle %4, i32 5)  ; CBufferLoadLegacy(handle,regIndex)
  %29 = extractvalue %dx.types.CBufRet.i32 %28, 0
  %30 = icmp sgt i32 %29, 0
  br i1 %30, label %31, label %88

; <label>:31                                      ; preds = %0
  br label %32

; <label>:32                                      ; preds = %79, %31
  %33 = phi float [ %80, %79 ], [ 0.000000e+00, %31 ]
  %34 = phi float [ %81, %79 ], [ 0.000000e+00, %31 ]
  %35 = phi float [ %82, %79 ], [ 0.000000e+00, %31 ]
  %36 = phi i32 [ %83, %79 ], [ 0, %31 ]
  %37 = call %dx.types.ResRet.f32 @dx.op.bufferLoad.f32(i32 68, %dx.types.Handle %2, i32 %36, i32 0)  ; BufferLoad(srv,index,wot)
  %38 = extractvalue %dx.types.ResRet.f32 %37, 0
  %39 = extractvalue %dx.types.ResRet.f32 %37, 1
  %40 = extractvalue %dx.types.ResRet.f32 %37, 2
  %41 = call %dx.types.ResRet.f32 @dx.op.bufferLoad.f32(i32 68, %dx.types.Handle %2, i32 %36, i32 12)  ; BufferLoad(srv,index,wot)
  %42 = extractvalue %dx.types.ResRet.f32 %41, 0
  %43 = call %dx.types.ResRet.f32 @dx.op.bufferLoad.f32(i32 68, %dx.types.Handle %2, i32 %36, i32 16)  ; BufferLoad(srv,index,wot)
  %44 = call %dx.types.ResRet.f32 @dx.op.bufferLoad.f32(i32 68, %dx.types.Handle %2, i32 %36, i32 28)  ; BufferLoad(srv,index,wot)
  %45 = extractvalue %dx.types.ResRet.f32 %44, 0
  %46 = fsub fast float %38, %10
  %47 = fsub fast float %39, %11
  %48 = fsub fast float %40, %12
  %49 = fmul fast float %46, %46
  %50 = fmul fast float %47, %47
  %51 = fadd fast float %49, %50
  %52 = fmul fast float %48, %48
  %53 = fadd fast float %51, %52
  %54 = call float @dx.op.unary.f32(i32 24, float %53)  ; Sqrt(value)
  %55 = fcmp fast ogt float %54, %42
  br i1 %55, label %79, label %56

; <label>:56                                      ; preds = %32
  %57 = extractvalue %dx.types.ResRet.f32 %43, 2
  %58 = extractvalue %dx.types.ResRet.f32 %43, 1
  %59 = extractvalue %dx.types.ResRet.f32 %43, 0
  %60 = fdiv fast float %46, %54
  %61 = fdiv fast float %47, %54
  %62 = fdiv fast float %48, %54
  %63 = call float @dx.op.dot3.f32(i32 55, float %25, float %26, float %27, float %60, float %61, float %62)  ; Dot3(ax,ay,az,bx,by,bz)
  %64 = call float @dx.op.unary.f32(i32 7, float %63)  ; Saturate(value)
  %65 = fmul fast float %45, %59
  %66 = fmul fast float %45, %58
  %67 = fmul fast float %45, %57
  %68 = fmul fast float %65, %64
  %69 = fmul fast float %66, %64
  %70 = fmul fast float %67, %64
  %71 = fmul fast float %54, %54
  %72 = fadd fast float %71, 1.000000e+00
  %73 = fdiv fast float %68, %72
  %74 = fdiv fast float %69, %72
  %75 = fdiv fast float %70, %72
  %76 = fadd fast float %73, %33
  %77 = fadd fast float %74, %34
  %78 = fadd fast float %75, %35
  br label %79

; <label>:79                                      ; preds = %56, %32
  %80 = phi float [ %33, %32 ], [ %76, %56 ]
  %81 = phi float [ %34, %32 ], [ %77, %56 ]
  %82 = phi float [ %35, %32 ], [ %78, %56 ]
  %83 = add nuw nsw i32 %36, 1
  %84 = call %dx.types.CBufRet.i32 @dx.op.cbufferLoadLegacy.i32(i32 59, %dx.types.Handle %4, i32 5)  ; CBufferLoadLegacy(handle,regIndex)
  %85 = extractvalue %dx.types.CBufRet.i32 %84, 0
  %86 = icmp slt i32 %83, %85
  br i1 %86, label %32, label %87

; <label>:87                                      ; preds = %79
  br label %88

; <label>:88                                      ; preds = %87, %0
  %89 = phi float [ 0.000000e+00, %0 ], [ %80, %87 ]
  %90 = phi float [ 0.000000e+00, %0 ], [ %81, %87 ]
  %91 = phi float [ 0.000000e+00, %0 ], [ %82, %87 ]
  %92 = call %dx.types.CBufRet.i32 @dx.op.cbufferLoadLegacy.i32(i32 59, %dx.types.Handle %4, i32 5)  ; CBufferLoadLegacy(handle,regIndex)
  %93 = extractvalue %dx.types.CBufRet.i32 %92, 1
  switch i32 %93, label %98 [
    i32 0, label %94
    i32 1, label %105
  ]

; <label>:94                                      ; preds = %88
  %95 = fmul fast float %89, %19
  %96 = fmul fast float %90, %20
  %97 = fmul fast float %91, %21
  br label %105

; <label>:98                                      ; preds = %88
  %99 = fmul fast float %25, 5.000000e-01
  %100 = fmul fast float %26, 5.000000e-01
  %101 = fmul fast float %27, 5.000000e-01
  %102 = fadd fast float %99, 5.000000e-01
  %103 = fadd fast float %100, 5.000000e-01
  %104 = fadd fast float %101, 5.000000e-01
  br label %105

; <label>:105                                     ; preds = %98, %94, %88
  %106 = phi float [ %102, %98 ], [ %95, %94 ], [ %89, %88 ]
  %107 = phi float [ %103, %98 ], [ %96, %94 ], [ %90, %88 ]
  %108 = phi float [ %104, %98 ], [ %97, %94 ], [ %91, %88 ]
  %109 = fcmp fast olt float %22, 0x3F847AE140000000
  br i1 %109, label %110, label %111

; <label>:110                                     ; preds = %105
  call void @dx.op.discard(i32 82, i1 true)  ; Discard(condition)
  br label %111

; <label>:111                                     ; preds = %110, %105
  %112 = call %dx.types.CBufRet.f32 @dx.op.cbufferLoadLegacy.f32(i32 59, %dx.types.Handle %4, i32 4)  ; CBufferLoadLegacy(handle,regIndex)
  %113 = extractvalue %dx.types.CBufRet.f32 %112, 3
  %114 = fmul fast float %113, %106
  %115 = fmul fast float %113, %107
  %116 = fmul fast float %113, %108
  call void @dx.op.storeOutput.f32(i32 5, i32 0, i32 0, i8 0, float %114)  ; StoreOutput(outputSigId,rowIndex,colIndex,value)
  call void @dx.op.storeOutput.f32(i32 5, i32 0, i32 0, i8 1, float %115)  ; StoreOutput(outputSigId,rowIndex,colIndex,value)
  call void @dx.op.storeOutput.f32(i32 5, i32 0, i32 0, i8 2, float %116)  ; StoreOutput(outputSigId,rowIndex,colIndex,value)
  call void @dx.op.storeOutput.f32(i32 5, i32 0, i32 0, i8 3, float %22)  ; StoreOutput(outputSigId,rowIndex,colIndex,value)
  ret void
}

; Function Attrs: nounwind readnone
declare float @dx.op.loadInput.f32(i32, i32, i32, i8, i32) #0

; Function Attrs: nounwind
declare void @dx.op.storeOutput.f32(i32, i32, i32, i8, float) #1

; Function Attrs: nounwind
declare void @dx.op.discard(i32, i1) #1

; Function Attrs: nounwind readonly
declare %dx.types.ResRet.f32 @dx.op.sample.f32(i32, %dx.types.Handle, %dx.types.Handle, float, float, float, float, i32, i32, i32, float) #2

; Function Attrs: nounwind readnone
declare float @dx.op.dot3.f32(i32, float, float, float, float, float, float) #0

; Function Attrs: nounwind readnone
declare float @dx.op.unary.f32(i32, float) #0

; Function Attrs: nounwind readonly
declare %dx.types.CBufRet.f32 @dx.op.cbufferLoadLegacy.f32(i32, %dx.types.Handle, i32) #2

; Function Attrs: nounwind readonly
declare %dx.types.CBufRet.i32 @dx.op.cbufferLoadLegacy.i32(i32, %dx.types.Handle, i32) #2

; Function Attrs: nounwind readonly
declare %dx.types.Handle @dx.op.createHandle(i32, i8, i32, i32, i1) #2

; Function Attrs: nounwind readonly
declare %dx.types.ResRet.f32 @dx.op.bufferLoad.f32(i32, %dx.types.Handle, i32, i32) #2

attributes #0 = { nounwind readnone }
attributes #1 = { nounwind }
attributes #2 = { nounwind readonly }

!llvm.ident = !{!0}
!dx.version = !{!1}
!dx.valver = !{!2}
!dx.shaderModel = !{!3}
!dx.resources = !{!4}
!dx.viewIdState = !{!14}
!dx.entryPoints = !{!15}

!0 = !{!"clang version 3.7 (tags/RELEASE_370/final)"}
!1 = !{i32 1, i32 0}
!2 = !{i32 1, i32 6}
!3 = !{!"ps", i32 6, i32 0}
!4 = !{!5, null, !10, !12}
!5 = !{!6, !8}
!6 = !{i32 0, %"class.StructuredBuffer<Light>"* undef, !"", i32 0, i32 0, i32 1, i32 12, i32 0, !7}
!7 = !{i32 1, i32 32}
!8 = !{i32 1, %"class.Texture2D<vector<float, 4> >"* undef, !"", i32 0, i32 1, i32 1, i32 2, i32 0, !9}
!9 = !{i32 0, i32 9}
!10 = !{!11}
!11 = !{i32 0, %hostlayout.Scene* undef, !"", i32 0, i32 0, i32 1, i32 96, null}
!12 = !{!13}
!13 = !{i32 0, %struct.SamplerState* undef, !"", i32 0, i32 0, i32 1, i32 0, null}
!14 = !{[16 x i32] [i32 14, i32 4, i32 0, i32 0, i32 0, i32 0, i32 7, i32 7, i32 7, i32 0, i32 7, i32 7, i32 7, i32 0, i32 15, i32 15]}
!15 = !{void ()* @PSMain, !"PSMain", !16, !4, !28}
!16 = !{!17, !25, null}
!17 = !{!18, !20, !22, !23}
!18 = !{i32 0, !"SV_Position", i8 9, i8 3, !19, i8 4, i32 1, i8 4, i32 0, i8 0, null}
!19 = !{i32 0}
!20 = !{i32 1, !"POSITION", i8 9, i8 0, !19, i8 2, i32 1, i8 3, i32 1, i8 0, !21}
!21 = !{i32 3, i32 7}
!22 = !{i32 2, !"NORMAL", i8 9, i8 0, !19, i8 2, i32 1, i8 3, i32 2, i8 0, !21}
!23 = !{i32 3, !"TEXCOORD", i8 9, i8 0, !19, i8 2, i32 1, i8 2, i32 3, i8 0, !24}
!24 = !{i32 3, i32 3}
!25 = !{!26}
!26 = !{i32 0, !"SV_Target", i8 9, i8 16, !19, i8 0, i32 1, i8 4, i32 0, i8 0, !27}
!27 = !{i32 3, i32 15}
!28 = !{i32 0, i64 16}
