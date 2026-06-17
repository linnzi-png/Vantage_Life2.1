// Custom Expo config plugin: fixes 'rnworklets/rnworklets.h' file not found
// during EAS iOS builds.
//
// Root cause: Expo's precompiled_modules.rb patches RNWorklets to use a
// pre-built xcframework. CocoaPods places the extracted framework slice at
// ${PODS_XCFRAMEWORKS_BUILD_DIR}/RNWorklets/RNWorklets.framework, but this
// path is not propagated into RNReanimated's FRAMEWORK_SEARCH_PATHS because
// the spec patch happens dynamically (post dependency-resolution).
//
// Fix: inject into the existing post_install block to add that path explicitly.
// We inject INTO the existing block (not append a new one) so that the
// react_native_post_install call in Expo's generated Podfile still runs.
//
// Template literal escaping note:
//   \${...} in a JS template literal → literal ${...} in the output string
//   (prevents JS from trying to interpolate PODS_XCFRAMEWORKS_BUILD_DIR)
//   #{...} is Ruby interpolation syntax — JS ignores it (not ${...})

const { withDangerousMod } = require('@expo/config-plugins');
const fs = require('fs');
const path = require('path');

const MARKER = '# worklets-xcframework-framework-search-path-fix';
const POST_INSTALL_OPENER = 'post_install do |installer|';

// Ruby code injected INTO the existing post_install block.
// \${PODS_XCFRAMEWORKS_BUILD_DIR} — the \$ prevents JS template interpolation;
// the Podfile receives the literal text ${PODS_XCFRAMEWORKS_BUILD_DIR} which
// Xcode expands at build time to the xcframework intermediates directory.
const INNER_CODE = `
  ${MARKER}
  installer.pods_project.targets.each do |target|
    next unless target.name == 'RNReanimated'
    target.build_configurations.each do |build_config|
      existing = build_config.build_settings['FRAMEWORK_SEARCH_PATHS'] || '$(inherited)'
      existing = existing.join(' ') if existing.is_a?(Array)
      next if existing.include?('XCFRAMEWORKS_BUILD_DIR')
      build_config.build_settings['FRAMEWORK_SEARCH_PATHS'] =
        "#{existing} \${PODS_XCFRAMEWORKS_BUILD_DIR}/RNWorklets"
    end
  end
`;

// Fallback: standalone block used only if the generated Podfile has no
// post_install block at all (should not happen with Expo SDK 55).
const STANDALONE_HOOK = `

${MARKER}
post_install do |installer|
  installer.pods_project.targets.each do |target|
    next unless target.name == 'RNReanimated'
    target.build_configurations.each do |build_config|
      existing = build_config.build_settings['FRAMEWORK_SEARCH_PATHS'] || '$(inherited)'
      existing = existing.join(' ') if existing.is_a?(Array)
      next if existing.include?('XCFRAMEWORKS_BUILD_DIR')
      build_config.build_settings['FRAMEWORK_SEARCH_PATHS'] =
        "#{existing} \${PODS_XCFRAMEWORKS_BUILD_DIR}/RNWorklets"
    end
  end
end
`;

/** @type {import('@expo/config-plugins').ConfigPlugin} */
function withWorkletsFix(config) {
  return withDangerousMod(config, [
    'ios',
    (config) => {
      const podfilePath = path.join(
        config.modRequest.platformProjectRoot,
        'Podfile'
      );
      let contents = fs.readFileSync(podfilePath, 'utf-8');

      // Idempotency guard — skip if already injected
      if (!contents.includes(MARKER)) {
        const insertIdx = contents.lastIndexOf(POST_INSTALL_OPENER);
        if (insertIdx !== -1) {
          // Inject into the existing post_install block right after the opener line.
          // This keeps react_native_post_install (and any other Expo post_install
          // code) intact — only one post_install block ever exists in the Podfile.
          const afterOpener = insertIdx + POST_INSTALL_OPENER.length;
          contents =
            contents.slice(0, afterOpener) +
            INNER_CODE +
            contents.slice(afterOpener);
        } else {
          // Fallback: no existing post_install found — append a standalone block
          contents += STANDALONE_HOOK;
        }
        fs.writeFileSync(podfilePath, contents);
      }

      return config;
    },
  ]);
}

module.exports = withWorkletsFix;
