// Custom Expo config plugin: fixes 'rnworklets/rnworklets.h' file not found
// during EAS iOS builds.
//
// Root cause: Expo's XCFramework switch replaces RNWorklets source compilation
// with a pre-built rnworklets.xcframework, but doesn't add the framework path
// to RNReanimated's FRAMEWORK_SEARCH_PATHS. This post_install hook does that.

const { withDangerousMod } = require('@expo/config-plugins');
const fs = require('fs');
const path = require('path');

const MARKER = '# worklets-xcframework-framework-search-path-fix';

const POSTINSTALL_HOOK = `
${MARKER}
post_install do |installer|
  installer.pods_project.targets.each do |target|
    next unless target.name == 'RNReanimated'
    target.build_configurations.each do |build_config|
      existing = build_config.build_settings['FRAMEWORK_SEARCH_PATHS'] || '$(inherited)'
      existing = existing.join(' ') if existing.is_a?(Array)
      next if existing.include?('RNWorklets')
      build_config.build_settings['FRAMEWORK_SEARCH_PATHS'] =
        "#{existing} $(PODS_CONFIGURATION_BUILD_DIR)/RNWorklets $(BUILT_PRODUCTS_DIR)"
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
      if (!contents.includes(MARKER)) {
        contents += POSTINSTALL_HOOK;
        fs.writeFileSync(podfilePath, contents);
      }
      return config;
    },
  ]);
}

module.exports = withWorkletsFix;
