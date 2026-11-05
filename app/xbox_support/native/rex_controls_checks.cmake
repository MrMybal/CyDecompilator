function(xbox_native_controls_checks game_target)
    set(native_root "${CMAKE_CURRENT_FUNCTION_LIST_DIR}")
    add_executable(native_controls_checks EXCLUDE_FROM_ALL
        "${native_root}/rex_controls_checks.cpp"
        "${native_root}/rex_controls.cpp"
        "${native_root}/rex_menu_bridge.cpp"
        "${native_root}/rex_animation.cpp"
        "${native_root}/rex_timing_checks.cpp"
        "${native_root}/rex_physics.cpp"
        "${native_root}/rex_test_flags.cpp")
    target_include_directories(native_controls_checks PRIVATE "${native_root}" "${CMAKE_CURRENT_SOURCE_DIR}/generated/default")
    target_compile_definitions(native_controls_checks PRIVATE XBOX_NATIVE_HALO=1 XBOX_NATIVE_SELF_TEST=1
        XBOX_NATIVE_PCH="${game_target}_pch.h" XBOX_NATIVE_INIT="${game_target}_init.h")
    target_link_libraries(native_controls_checks PRIVATE ${game_target}_recomp rex::runtime)
    rexglue_apply_target_settings(native_controls_checks)
endfunction()
