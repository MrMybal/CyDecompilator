"""Local host-query recovery and segmented queries for the pinned GPU backend."""

def patch(contents, header, module, replace_once):
    start = contents.index('bool D3D12CommandProcessor::ExecutePacketType3_EVENT_WRITE_ZPD(')
    end = contents.index('\nbool D3D12CommandProcessor::PushTransitionBarrier(', start)
    implementation = (module / 'native/rex_occlusion_packet.inl').read_text(encoding='utf-8')
    contents = contents[:start] + implementation + '\n' + contents[end:]
    # A query crossing a submission boundary is split into host queries, then
    # summed after the last fence. Previously EndSubmission silently lost it.
    block = '''    if (active_occlusion_query_.valid && occlusion_query_heap_) {
      deferred_command_list_.D3DEndQuery(occlusion_query_heap_.Get(), D3D12_QUERY_TYPE_OCCLUSION,
                                         active_occlusion_query_.host_index);
      active_occlusion_query_ = {};
    }'''
    replacement = '''    if (active_occlusion_query_.valid && occlusion_query_heap_ && active_occlusion_query_.host_index != UINT32_MAX) {
      auto index = active_occlusion_query_.host_index;
      deferred_command_list_.D3DEndQuery(occlusion_query_heap_.Get(), D3D12_QUERY_TYPE_OCCLUSION, index);
      deferred_command_list_.D3DResolveQueryData(occlusion_query_heap_.Get(), D3D12_QUERY_TYPE_OCCLUSION,
          index, 1, occlusion_query_readback_.Get(), sizeof(uint64_t) * index);
      active_occlusion_query_.segments.push_back(index);
      active_occlusion_query_.host_index = UINT32_MAX;
    }'''
    contents = replace_once(contents, block, replacement)
    contents = replace_once(contents, '    deferred_command_list_.Reset();', '''    deferred_command_list_.Reset();
    if (active_occlusion_query_.valid && active_occlusion_query_.host_index == UINT32_MAX) {
      uint32_t index;
      if (!AcquireOcclusionQueryIndex(index)) return false;
      active_occlusion_query_.host_index = index;
      deferred_command_list_.D3DBeginQuery(occlusion_query_heap_.Get(), D3D12_QUERY_TYPE_OCCLUSION, index);
    }''')
    contents = replace_once(contents,
        '  uint32_t host_index = active_occlusion_query_.host_index;\n  active_occlusion_query_ = {};',
        '  auto segments = std::move(active_occlusion_query_.segments);\n'
        '  uint32_t host_index = active_occlusion_query_.host_index;\n  active_occlusion_query_ = {};')
    contents = replace_once(contents,
        '''  deferred_command_list_.D3DEndQuery(occlusion_query_heap_.Get(), D3D12_QUERY_TYPE_OCCLUSION,
                                     host_index);
  deferred_command_list_.D3DResolveQueryData(
      occlusion_query_heap_.Get(), D3D12_QUERY_TYPE_OCCLUSION, host_index, 1,
      occlusion_query_readback_.Get(), sizeof(uint64_t) * host_index);''',
        '''  if (host_index != UINT32_MAX) {
    deferred_command_list_.D3DEndQuery(occlusion_query_heap_.Get(), D3D12_QUERY_TYPE_OCCLUSION, host_index);
    deferred_command_list_.D3DResolveQueryData(occlusion_query_heap_.Get(), D3D12_QUERY_TYPE_OCCLUSION,
        host_index, 1, occlusion_query_readback_.Get(), sizeof(uint64_t) * host_index);
    segments.push_back(host_index);
  }''')
    contents = replace_once(contents, '  uint64_t samples = occlusion_query_readback_mapping_[host_index];',
        '  uint64_t samples = 0;\n  for (uint32_t index : segments) samples += occlusion_query_readback_mapping_[index];')
    contents = replace_once(contents,
        '  if (active_occlusion_query_.valid && occlusion_query_heap_) {',
        '  if (active_occlusion_query_.valid && occlusion_query_heap_ && active_occlusion_query_.host_index != UINT32_MAX) {')
    header = replace_once(header, '    bool valid = false;\n  } active_occlusion_query_;',
        '    bool valid = false;\n    std::vector<uint32_t> segments;\n  } active_occlusion_query_;\n'
        '  uint32_t occlusion_snapshot_counter_ = 0;')
    return contents, header
