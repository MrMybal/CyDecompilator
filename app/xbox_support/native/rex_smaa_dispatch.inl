// Runs inside D3D12CommandProcessor's guest-output refresh callback, after
// gamma conversion and before handing the image to the presenter/overlay.
bool native_smaa_done = false;
if (static_cast<int>(swap_post_effect) == 3)
  native_smaa_done = [&]() -> bool {
    if (!native_smaa) {
      native_smaa = std::make_unique<NativeSmaaResources>();
      if (!native_smaa->Initialize(provider)) {
        native_smaa.reset();
        REXGPU_ERROR("[xbox-native] SMAA pipeline creation failed");
        return false;
      }
    }
    auto &s = *native_smaa;
    if (!s.edges || !s.weights || s.width != guest_output_width ||
        s.height != guest_output_height) {
      // Defer old attachments until their last submission has completed.
      for (auto *old : {std::addressof(s.edges), std::addressof(s.weights)})
        if (*old) {
          (*old)->AddRef();
          resources_for_deletion_.emplace_back(s.submission, old->Get());
          old->Reset();
        }
      if (!NativeSmaaResources::Texture(device, s.edges, guest_output_width,
                                        guest_output_height,
                                        DXGI_FORMAT_R8G8B8A8_UNORM, true) ||
          !NativeSmaaResources::Texture(device, s.weights, guest_output_width,
                                        guest_output_height,
                                        DXGI_FORMAT_R8G8B8A8_UNORM, true))
        return false;
      s.width = guest_output_width;
      s.height = guest_output_height;
      REXGPU_INFO(
          "[xbox-native] Native SMAA 1x High: {}x{}, three compute passes",
          s.width, s.height);
    }
    s.submission = submission_current_;
    auto &descriptors = fxaa_descriptors;
    ID3D12Resource *targets[] = {s.edges.Get(), s.weights.Get(),
                                 guest_output_resource};
    for (int i = 0; i < 3; ++i) {
      D3D12_UNORDERED_ACCESS_VIEW_DESC d{};
      d.Format = i == 2 ? ui::d3d12::D3D12Presenter::kGuestOutputFormat
                        : DXGI_FORMAT_R8G8B8A8_UNORM;
      d.ViewDimension = D3D12_UAV_DIMENSION_TEXTURE2D;
      device->CreateUnorderedAccessView(targets[i], nullptr, &d,
                                        descriptors[i].first);
    }
    ID3D12Resource *inputs[] = {fxaa_source_texture_.Get(), s.edges.Get(),
                                s.weights.Get(), s.area.Get(), s.search.Get()};
    DXGI_FORMAT formats[] = {kFxaaSourceTextureFormat,
                             DXGI_FORMAT_R8G8B8A8_UNORM,
                             DXGI_FORMAT_R8G8B8A8_UNORM, DXGI_FORMAT_R8G8_UNORM,
                             DXGI_FORMAT_R8_UNORM};
    for (int i = 0; i < 5; ++i) {
      D3D12_SHADER_RESOURCE_VIEW_DESC d{};
      d.Format = formats[i];
      d.ViewDimension = D3D12_SRV_DIMENSION_TEXTURE2D;
      d.Shader4ComponentMapping = D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;
      d.Texture2D.MipLevels = 1;
      device->CreateShaderResourceView(inputs[i], &d, descriptors[i + 3].first);
    }
    if (!s.uploaded) {
      uint32_t widths[] = {AREATEX_WIDTH, SEARCHTEX_WIDTH},
               heights[] = {AREATEX_HEIGHT, SEARCHTEX_HEIGHT}, bytes[] = {2, 1};
      for (int i = 0; i < 2; ++i) {
        D3D12_TEXTURE_COPY_LOCATION src{}, dst{};
        src.pResource = s.uploads[i].Get();
        src.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;
        src.PlacedFootprint.Footprint = {formats[i + 3], widths[i], heights[i],
                                         1,
                                         (widths[i] * bytes[i] + 255) & ~255u};
        dst.pResource = inputs[i + 3];
        dst.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
        deferred_command_list_.D3DCopyTextureRegion(&dst, 0, 0, 0, &src,
                                                    nullptr);
        PushTransitionBarrier(inputs[i + 3], D3D12_RESOURCE_STATE_COPY_DEST,
                              D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
      }
      s.uploaded = true;
    }
    deferred_command_list_.D3DSetComputeRootSignature(s.root.Get());
    float metrics[] = {1.f / s.width, 1.f / s.height, float(s.width),
                       float(s.height)};
    deferred_command_list_.D3DSetComputeRoot32BitConstants(0, 4, metrics, 0);
    // Bindless one-use descriptors can be recycled in arbitrary order. Bind
    // every SRV separately rather than assuming a contiguous descriptor range.
    for(int i=0;i<5;++i)
      deferred_command_list_.D3DSetComputeRootDescriptorTable(
          UINT(2+i), descriptors[3+i].second);
    for (int pass = 0; pass < 3; ++pass) {
      if (pass < 2)
        PushTransitionBarrier(targets[pass],
                              D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,
                              D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
      deferred_command_list_.D3DSetComputeRootDescriptorTable(
          1, descriptors[pass].second);
      SetExternalPipeline(s.pipelines[pass].Get());
      SubmitBarriers();
      deferred_command_list_.D3DDispatch(group_count_x, group_count_y, 1);
      if (pass < 2)
        PushTransitionBarrier(targets[pass],
                              D3D12_RESOURCE_STATE_UNORDERED_ACCESS,
                              D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
    }
    return true;
  }();
if (!native_smaa_done) {
  SetExternalPipeline(swap_post_effect == SwapPostEffect::kFxaaExtreme
                          ? fxaa_extreme_pipeline_.Get()
                          : fxaa_pipeline_.Get());
  SubmitBarriers();
  deferred_command_list_.D3DDispatch(group_count_x, group_count_y, 1);
}
