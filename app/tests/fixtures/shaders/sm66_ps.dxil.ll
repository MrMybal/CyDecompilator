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
; shader hash: ae1feb192fa64c1901621a0dc0080b27
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
%dx.types.ResBind = type { i32, i32, i32, i8 }
%dx.types.ResourceProperties = type { i32, i32 }
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
  %1 = call %dx.types.Handle @dx.op.createHandleFromBinding(i32 217, %dx.types.ResBind { i32 1, i32 1, i32 0, i8 0 }, i32 1, i1 false)  ; CreateHandleFromBinding(bind,index,nonUniformIndex)
  %2 = call %dx.types.Handle @dx.op.createHandleFromBinding(i32 217, %dx.types.ResBind zeroinitializer, i32 0, i1 false)  ; CreateHandleFromBinding(bind,index,nonUniformIndex)
  %3 = call %dx.types.Handle @dx.op.createHandleFromBinding(i32 217, %dx.types.ResBind { i32 0, i32 0, i32 0, i8 3 }, i32 0, i1 false)  ; CreateHandleFromBinding(bind,index,nonUniformIndex)
  %4 = call %dx.types.Handle @dx.op.createHandleFromBinding(i32 217, %dx.types.ResBind { i32 0, i32 0, i32 0, i8 2 }, i32 0, i1 false)  ; CreateHandleFromBinding(bind,index,nonUniformIndex)
  %5 = call %dx.types.Handle @dx.op.annotateHandle(i32 216, %dx.types.Handle %4, %dx.types.ResourceProperties { i32 13, i32 96 })  ; AnnotateHandle(res,props)  resource: CBuffer
  %6 = call float @dx.op.loadInput.f32(i32 4, i32 3, i32 0, i8 0, i32 undef)  ; LoadInput(inputSigId,rowIndex,colIndex,gsVertexAxis)
  %7 = call float @dx.op.loadInput.f32(i32 4, i32 3, i32 0, i8 1, i32 undef)  ; LoadInput(inputSigId,rowIndex,colIndex,gsVertexAxis)
  %8 = call float @dx.op.loadInput.f32(i32 4, i32 2, i32 0, i8 0, i32 undef)  ; LoadInput(inputSigId,rowIndex,colIndex,gsVertexAxis)
  %9 = call float @dx.op.loadInput.f32(i32 4, i32 2, i32 0, i8 1, i32 undef)  ; LoadInput(inputSigId,rowIndex,colIndex,gsVertexAxis)
  %10 = call float @dx.op.loadInput.f32(i32 4, i32 2, i32 0, i8 2, i32 undef)  ; LoadInput(inputSigId,rowIndex,colIndex,gsVertexAxis)
  %11 = call float @dx.op.loadInput.f32(i32 4, i32 1, i32 0, i8 0, i32 undef)  ; LoadInput(inputSigId,rowIndex,colIndex,gsVertexAxis)
  %12 = call float @dx.op.loadInput.f32(i32 4, i32 1, i32 0, i8 1, i32 undef)  ; LoadInput(inputSigId,rowIndex,colIndex,gsVertexAxis)
  %13 = call float @dx.op.loadInput.f32(i32 4, i32 1, i32 0, i8 2, i32 undef)  ; LoadInput(inputSigId,rowIndex,colIndex,gsVertexAxis)
  %14 = call %dx.types.CBufRet.f32 @dx.op.cbufferLoadLegacy.f32(i32 59, %dx.types.Handle %5, i32 5)  ; CBufferLoadLegacy(handle,regIndex)
  %15 = extractvalue %dx.types.CBufRet.f32 %14, 2
  %16 = extractvalue %dx.types.CBufRet.f32 %14, 3
  %17 = fadd fast float %15, %6
  %18 = fadd fast float %16, %7
  %19 = call %dx.types.Handle @dx.op.annotateHandle(i32 216, %dx.types.Handle %1, %dx.types.ResourceProperties { i32 2, i32 1033 })  ; AnnotateHandle(res,props)  resource: Texture2D<4xF32>
  %20 = call %dx.types.Handle @dx.op.annotateHandle(i32 216, %dx.types.Handle %3, %dx.types.ResourceProperties { i32 14, i32 0 })  ; AnnotateHandle(res,props)  resource: SamplerState
  %21 = call %dx.types.ResRet.f32 @dx.op.sample.f32(i32 60, %dx.types.Handle %19, %dx.types.Handle %20, float %17, float %18, float undef, float undef, i32 0, i32 0, i32 undef, float undef)  ; Sample(srv,sampler,coord0,coord1,coord2,coord3,offset0,offset1,offset2,clamp)
  %22 = extractvalue %dx.types.ResRet.f32 %21, 0
  %23 = extractvalue %dx.types.ResRet.f32 %21, 1
  %24 = extractvalue %dx.types.ResRet.f32 %21, 2
  %25 = extractvalue %dx.types.ResRet.f32 %21, 3
  %26 = call float @dx.op.dot3.f32(i32 55, float %8, float %9, float %10, float %8, float %9, float %10)  ; Dot3(ax,ay,az,bx,by,bz)
  %27 = call float @dx.op.unary.f32(i32 25, float %26)  ; Rsqrt(value)
  %28 = fmul fast float %27, %8
  %29 = fmul fast float %27, %9
  %30 = fmul fast float %27, %10
  %31 = call %dx.types.CBufRet.i32 @dx.op.cbufferLoadLegacy.i32(i32 59, %dx.types.Handle %5, i32 5)  ; CBufferLoadLegacy(handle,regIndex)
  %32 = extractvalue %dx.types.CBufRet.i32 %31, 0
  %33 = icmp sgt i32 %32, 0
  br i1 %33, label %34, label %36

; <label>:34                                      ; preds = %0
  br label %42

; <label>:35                                      ; preds = %90
  br label %36

; <label>:36                                      ; preds = %35, %0
  %37 = phi float [ 0.000000e+00, %0 ], [ %91, %35 ]
  %38 = phi float [ 0.000000e+00, %0 ], [ %92, %35 ]
  %39 = phi float [ 0.000000e+00, %0 ], [ %93, %35 ]
  %40 = call %dx.types.CBufRet.i32 @dx.op.cbufferLoadLegacy.i32(i32 59, %dx.types.Handle %5, i32 5)  ; CBufferLoadLegacy(handle,regIndex)
  %41 = extractvalue %dx.types.CBufRet.i32 %40, 1
  switch i32 %41, label %102 [
    i32 0, label %98
    i32 1, label %109
  ]

; <label>:42                                      ; preds = %90, %34
  %43 = phi float [ %91, %90 ], [ 0.000000e+00, %34 ]
  %44 = phi float [ %92, %90 ], [ 0.000000e+00, %34 ]
  %45 = phi float [ %93, %90 ], [ 0.000000e+00, %34 ]
  %46 = phi i32 [ %94, %90 ], [ 0, %34 ]
  %47 = call %dx.types.Handle @dx.op.annotateHandle(i32 216, %dx.types.Handle %2, %dx.types.ResourceProperties { i32 524, i32 32 })  ; AnnotateHandle(res,props)  resource: StructuredBuffer<stride=32>
  %48 = call %dx.types.ResRet.f32 @dx.op.rawBufferLoad.f32(i32 139, %dx.types.Handle %47, i32 %46, i32 0, i8 7, i32 4)  ; RawBufferLoad(srv,index,elementOffset,mask,alignment)
  %49 = extractvalue %dx.types.ResRet.f32 %48, 0
  %50 = extractvalue %dx.types.ResRet.f32 %48, 1
  %51 = extractvalue %dx.types.ResRet.f32 %48, 2
  %52 = call %dx.types.ResRet.f32 @dx.op.rawBufferLoad.f32(i32 139, %dx.types.Handle %47, i32 %46, i32 12, i8 1, i32 4)  ; RawBufferLoad(srv,index,elementOffset,mask,alignment)
  %53 = extractvalue %dx.types.ResRet.f32 %52, 0
  %54 = call %dx.types.ResRet.f32 @dx.op.rawBufferLoad.f32(i32 139, %dx.types.Handle %47, i32 %46, i32 16, i8 7, i32 4)  ; RawBufferLoad(srv,index,elementOffset,mask,alignment)
  %55 = call %dx.types.ResRet.f32 @dx.op.rawBufferLoad.f32(i32 139, %dx.types.Handle %47, i32 %46, i32 28, i8 1, i32 4)  ; RawBufferLoad(srv,index,elementOffset,mask,alignment)
  %56 = extractvalue %dx.types.ResRet.f32 %55, 0
  %57 = fsub fast float %49, %11
  %58 = fsub fast float %50, %12
  %59 = fsub fast float %51, %13
  %60 = fmul fast float %57, %57
  %61 = fmul fast float %58, %58
  %62 = fadd fast float %60, %61
  %63 = fmul fast float %59, %59
  %64 = fadd fast float %62, %63
  %65 = call float @dx.op.unary.f32(i32 24, float %64)  ; Sqrt(value)
  %66 = fcmp fast ogt float %65, %53
  br i1 %66, label %90, label %67

; <label>:67                                      ; preds = %42
  %68 = extractvalue %dx.types.ResRet.f32 %54, 2
  %69 = extractvalue %dx.types.ResRet.f32 %54, 1
  %70 = extractvalue %dx.types.ResRet.f32 %54, 0
  %71 = fdiv fast float %57, %65
  %72 = fdiv fast float %58, %65
  %73 = fdiv fast float %59, %65
  %74 = call float @dx.op.dot3.f32(i32 55, float %28, float %29, float %30, float %71, float %72, float %73)  ; Dot3(ax,ay,az,bx,by,bz)
  %75 = call float @dx.op.unary.f32(i32 7, float %74)  ; Saturate(value)
  %76 = fmul fast float %56, %70
  %77 = fmul fast float %56, %69
  %78 = fmul fast float %56, %68
  %79 = fmul fast float %76, %75
  %80 = fmul fast float %77, %75
  %81 = fmul fast float %78, %75
  %82 = fmul fast float %65, %65
  %83 = fadd fast float %82, 1.000000e+00
  %84 = fdiv fast float %79, %83
  %85 = fdiv fast float %80, %83
  %86 = fdiv fast float %81, %83
  %87 = fadd fast float %84, %43
  %88 = fadd fast float %85, %44
  %89 = fadd fast float %86, %45
  br label %90

; <label>:90                                      ; preds = %67, %42
  %91 = phi float [ %87, %67 ], [ %43, %42 ]
  %92 = phi float [ %88, %67 ], [ %44, %42 ]
  %93 = phi float [ %89, %67 ], [ %45, %42 ]
  %94 = add nuw nsw i32 %46, 1
  %95 = call %dx.types.CBufRet.i32 @dx.op.cbufferLoadLegacy.i32(i32 59, %dx.types.Handle %5, i32 5)  ; CBufferLoadLegacy(handle,regIndex)
  %96 = extractvalue %dx.types.CBufRet.i32 %95, 0
  %97 = icmp slt i32 %94, %96
  br i1 %97, label %42, label %35

; <label>:98                                      ; preds = %36
  %99 = fmul fast float %37, %22
  %100 = fmul fast float %38, %23
  %101 = fmul fast float %39, %24
  br label %109

; <label>:102                                     ; preds = %36
  %103 = fmul fast float %28, 5.000000e-01
  %104 = fmul fast float %29, 5.000000e-01
  %105 = fmul fast float %30, 5.000000e-01
  %106 = fadd fast float %103, 5.000000e-01
  %107 = fadd fast float %104, 5.000000e-01
  %108 = fadd fast float %105, 5.000000e-01
  br label %109

; <label>:109                                     ; preds = %102, %98, %36
  %110 = phi float [ %106, %102 ], [ %99, %98 ], [ %37, %36 ]
  %111 = phi float [ %107, %102 ], [ %100, %98 ], [ %38, %36 ]
  %112 = phi float [ %108, %102 ], [ %101, %98 ], [ %39, %36 ]
  %113 = fcmp fast olt float %25, 0x3F847AE140000000
  br i1 %113, label %114, label %115

; <label>:114                                     ; preds = %109
  call void @dx.op.discard(i32 82, i1 true)  ; Discard(condition)
  br label %115

; <label>:115                                     ; preds = %114, %109
  %116 = call %dx.types.CBufRet.f32 @dx.op.cbufferLoadLegacy.f32(i32 59, %dx.types.Handle %5, i32 4)  ; CBufferLoadLegacy(handle,regIndex)
  %117 = extractvalue %dx.types.CBufRet.f32 %116, 3
  %118 = fmul fast float %117, %110
  %119 = fmul fast float %117, %111
  %120 = fmul fast float %117, %112
  call void @dx.op.storeOutput.f32(i32 5, i32 0, i32 0, i8 0, float %118)  ; StoreOutput(outputSigId,rowIndex,colIndex,value)
  call void @dx.op.storeOutput.f32(i32 5, i32 0, i32 0, i8 1, float %119)  ; StoreOutput(outputSigId,rowIndex,colIndex,value)
  call void @dx.op.storeOutput.f32(i32 5, i32 0, i32 0, i8 2, float %120)  ; StoreOutput(outputSigId,rowIndex,colIndex,value)
  call void @dx.op.storeOutput.f32(i32 5, i32 0, i32 0, i8 3, float %25)  ; StoreOutput(outputSigId,rowIndex,colIndex,value)
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
declare %dx.types.ResRet.f32 @dx.op.rawBufferLoad.f32(i32, %dx.types.Handle, i32, i32, i8, i32) #2

; Function Attrs: nounwind readonly
declare %dx.types.CBufRet.f32 @dx.op.cbufferLoadLegacy.f32(i32, %dx.types.Handle, i32) #2

; Function Attrs: nounwind readonly
declare %dx.types.CBufRet.i32 @dx.op.cbufferLoadLegacy.i32(i32, %dx.types.Handle, i32) #2

; Function Attrs: nounwind readnone
declare %dx.types.Handle @dx.op.annotateHandle(i32, %dx.types.Handle, %dx.types.ResourceProperties) #0

; Function Attrs: nounwind readnone
declare %dx.types.Handle @dx.op.createHandleFromBinding(i32, %dx.types.ResBind, i32, i1) #0

attributes #0 = { nounwind readnone }
attributes #1 = { nounwind }
attributes #2 = { nounwind readonly }

!llvm.ident = !{!0}
!dx.version = !{!1}
!dx.valver = !{!1}
!dx.shaderModel = !{!2}
!dx.resources = !{!3}
!dx.viewIdState = !{!13}
!dx.entryPoints = !{!14}

!0 = !{!"clang version 3.7 (tags/RELEASE_370/final)"}
!1 = !{i32 1, i32 6}
!2 = !{!"ps", i32 6, i32 6}
!3 = !{!4, null, !9, !11}
!4 = !{!5, !7}
!5 = !{i32 0, %"class.StructuredBuffer<Light>"* undef, !"", i32 0, i32 0, i32 1, i32 12, i32 0, !6}
!6 = !{i32 1, i32 32}
!7 = !{i32 1, %"class.Texture2D<vector<float, 4> >"* undef, !"", i32 0, i32 1, i32 1, i32 2, i32 0, !8}
!8 = !{i32 0, i32 9}
!9 = !{!10}
!10 = !{i32 0, %hostlayout.Scene* undef, !"", i32 0, i32 0, i32 1, i32 96, null}
!11 = !{!12}
!12 = !{i32 0, %struct.SamplerState* undef, !"", i32 0, i32 0, i32 1, i32 0, null}
!13 = !{[16 x i32] [i32 14, i32 4, i32 0, i32 0, i32 0, i32 0, i32 7, i32 7, i32 7, i32 0, i32 7, i32 7, i32 7, i32 0, i32 15, i32 15]}
!14 = !{void ()* @PSMain, !"PSMain", !15, !3, !27}
!15 = !{!16, !24, null}
!16 = !{!17, !19, !21, !22}
!17 = !{i32 0, !"SV_Position", i8 9, i8 3, !18, i8 4, i32 1, i8 4, i32 0, i8 0, null}
!18 = !{i32 0}
!19 = !{i32 1, !"POSITION", i8 9, i8 0, !18, i8 2, i32 1, i8 3, i32 1, i8 0, !20}
!20 = !{i32 3, i32 7}
!21 = !{i32 2, !"NORMAL", i8 9, i8 0, !18, i8 2, i32 1, i8 3, i32 2, i8 0, !20}
!22 = !{i32 3, !"TEXCOORD", i8 9, i8 0, !18, i8 2, i32 1, i8 2, i32 3, i8 0, !23}
!23 = !{i32 3, i32 3}
!24 = !{!25}
!25 = !{i32 0, !"SV_Target", i8 9, i8 16, !18, i8 0, i32 1, i8 4, i32 0, i8 0, !26}
!26 = !{i32 3, i32 15}
!27 = !{i32 0, i64 16}
