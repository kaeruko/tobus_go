#!/usr/bin/env ruby
# frozen_string_literal: true

# Deterministically expands the stock Runner Xcode configurations into
# Debug/Profile/Release configurations for tokyo, nagoya and sendai.
#
# The script is intentionally fail-fast: it only knows the exact configuration
# IDs in this repository and refuses a partially generated or unexpected state.

PROJECT_PATH = File.expand_path('../ios/Runner.xcodeproj/project.pbxproj', __dir__)
PODFILE_PATH = File.expand_path('../ios/Podfile', __dir__)
CHECK_ONLY = ARGV == ['--check']
unless ARGV.empty? || CHECK_ONLY
  abort 'usage: ruby scripts/configure_ios_flavors.rb [--check]'
end

podfile = File.read(PODFILE_PATH, encoding: 'UTF-8')
unless podfile.include?("if target.name == 'geolocator_apple'") &&
       podfile.include?("BYPASS_PERMISSION_LOCATION_ALWAYS=1")
  abort 'ios/Podfile must disable geolocator_apple Always location permission with BYPASS_PERMISSION_LOCATION_ALWAYS=1'
end

BASE_PROJECT_CONFIGS = {
  'Debug' => '97C147031CF9000F007C117D',
  'Release' => '97C147041CF9000F007C117D',
  'Profile' => '249021D3217E4FDB00AE95B9'
}.freeze

BASE_RUNNER_CONFIGS = {
  'Debug' => '97C147061CF9000F007C117D',
  'Release' => '97C147071CF9000F007C117D',
  'Profile' => '249021D4217E4FDB00AE95B9'
}.freeze

BASE_TEST_CONFIGS = {
  'Debug' => '331C8088294A63A400263BE5',
  'Release' => '331C8089294A63A400263BE5',
  'Profile' => '331C808A294A63A400263BE5'
}.freeze

CITIES = {
  'tokyo' => {
    bundle_id: 'jp.cloxs.go.tokyo',
    display_name: '都営でGO',
    app_icon_name: 'AppIconTokyo',
    exclude_tokyo_firebase_plist: false
  },
  'nagoya' => {
    bundle_id: 'jp.cloxs.nagoyago',
    display_name: '名古屋でGO',
    app_icon_name: 'AppIconNagoya',
    exclude_tokyo_firebase_plist: true
  },
  'sendai' => {
    bundle_id: 'jp.cloxs.go.sendai',
    display_name: '仙台でGO',
    app_icon_name: 'AppIconSendai',
    exclude_tokyo_firebase_plist: true
  }
}.freeze

BUILD_KINDS = %w[Debug Release Profile].freeze

PROJECT_IDS = {}
RUNNER_IDS = {}
TEST_IDS = {}
CITIES.keys.each_with_index do |city, city_index|
  BUILD_KINDS.each_with_index do |kind, kind_index|
    ordinal = city_index * BUILD_KINDS.length + kind_index + 1
    PROJECT_IDS[[kind, city]] = format('A1000000000000000000%04X', ordinal)
    RUNNER_IDS[[kind, city]] = format('B1000000000000000000%04X', ordinal)
    TEST_IDS[[kind, city]] = format('C1000000000000000000%04X', ordinal)
  end
end

def config_block_present?(text, id)
  text.include?("\t\t#{id} /*")
end

def extract_config_block(text, id)
  pattern = /^\t\t#{Regexp.escape(id)} \/\* .*? \*\/ = \{\n.*?^\t\t\};$/m
  match = text.match(pattern)
  abort "Could not find Xcode configuration block #{id}" unless match
  match[0]
end

def rename_config_block(block, old_id:, new_id:, old_name:, new_name:)
  result = block.sub(/^\t\t#{Regexp.escape(old_id)} \/\* #{Regexp.escape(old_name)} \*\//,
                     "\t\t#{new_id} /* #{new_name} */")
  result = result.sub(/\n\t\t\tname = #{Regexp.escape(old_name)};\n\t\t\};\z/,
                      "\n\t\t\tname = #{new_name};\n\t\t};")
  abort "Failed to rename Xcode configuration #{old_name} -> #{new_name}" if result == block
  result
end

def ensure_runner_city_settings(block, city:, display_name:, bundle_id:, app_icon_name:, exclude_plist:)
  result = block

  app_icon_pattern = /\t\t\t\tASSETCATALOG_COMPILER_APPICON_NAME = [^;]+;/
  abort 'Runner configuration is missing app icon setting' unless result.match?(app_icon_pattern)
  result = result.sub(
    app_icon_pattern,
    "\t\t\t\tASSETCATALOG_COMPILER_APPICON_NAME = #{app_icon_name};"
  )
  app_icon_line = "\t\t\t\tASSETCATALOG_COMPILER_APPICON_NAME = #{app_icon_name};\n"

  if result.include?('APP_CITY = ')
    result = result.sub(/\t\t\t\tAPP_CITY = [^;]+;/,
                        "\t\t\t\tAPP_CITY = #{city};")
  else
    result = result.sub(app_icon_line, "#{app_icon_line}\t\t\t\tAPP_CITY = #{city};\n")
  end

  if result.include?('APP_DISPLAY_NAME = ')
    result = result.sub(/\t\t\t\tAPP_DISPLAY_NAME = .*?;/,
                        "\t\t\t\tAPP_DISPLAY_NAME = \"#{display_name}\";")
  else
    city_line = "\t\t\t\tAPP_CITY = #{city};\n"
    abort 'Runner configuration is missing generated APP_CITY anchor' unless result.include?(city_line)
    result = result.sub(city_line,
                        "#{city_line}\t\t\t\tAPP_DISPLAY_NAME = \"#{display_name}\";\n")
  end

  bundle_pattern = /\t\t\t\tPRODUCT_BUNDLE_IDENTIFIER = [^;]+;/
  abort 'Runner configuration is missing PRODUCT_BUNDLE_IDENTIFIER' unless result.match?(bundle_pattern)
  result = result.sub(bundle_pattern,
                      "\t\t\t\tPRODUCT_BUNDLE_IDENTIFIER = #{bundle_id};")

  exclusion_line = "\t\t\t\tEXCLUDED_SOURCE_FILE_NAMES = \"GoogleService-Info.plist\";\n"
  if exclude_plist
    unless result.include?(exclusion_line)
      bitcode_anchor = "\t\t\t\tENABLE_BITCODE = NO;\n"
      abort 'Runner configuration is missing ENABLE_BITCODE anchor' unless result.include?(bitcode_anchor)
      result = result.sub(bitcode_anchor, "#{bitcode_anchor}#{exclusion_line}")
    end
  else
    result = result.sub(exclusion_line, '')
  end
  result
end

def ensure_test_city_settings(block, bundle_id:)
  result = block
  bundle_pattern = /\t\t\t\tPRODUCT_BUNDLE_IDENTIFIER = [^;]+;/
  abort 'RunnerTests configuration is missing PRODUCT_BUNDLE_IDENTIFIER' unless result.match?(bundle_pattern)
  result = result.sub(
    bundle_pattern,
    "\t\t\t\tPRODUCT_BUNDLE_IDENTIFIER = #{bundle_id}.RunnerTests;"
  )
  abort 'RunnerTests configuration must declare SWIFT_VERSION = 5.0' unless result.include?(
    "\t\t\t\tSWIFT_VERSION = 5.0;"
  )
  result
end

def append_configuration_entries(text, list_id, anchor_entry, entries)
  list_pattern = /(\t\t#{Regexp.escape(list_id)} \/\* Build configuration list .*? = \{\n\t\t\tisa = XCConfigurationList;\n\t\t\tbuildConfigurations = \(\n)(.*?)(\t\t\t\);)/m
  match = text.match(list_pattern)
  abort "Could not find configuration list #{list_id}" unless match
  body = match[2]
  return text if entries.all? { |entry| body.include?(entry) }

  unless body.include?(anchor_entry)
    abort "Configuration list #{list_id} is missing anchor #{anchor_entry.strip}"
  end
  if entries.any? { |entry| body.include?(entry) }
    abort "Configuration list #{list_id} is partially generated"
  end

  replacement_body = body + entries.join
  text.sub(list_pattern, "#{match[1]}#{replacement_body}#{match[3]}")
end

original = File.read(PROJECT_PATH, encoding: 'UTF-8')
text = original.dup

# Keep the legacy unflavored Runner target explicitly named Tokyo so changing
# Info.plist to $(APP_DISPLAY_NAME) does not change the existing app.
BASE_RUNNER_CONFIGS.each do |_kind, id|
  block = extract_config_block(text, id)
  tokyo = CITIES.fetch('tokyo')
  updated = ensure_runner_city_settings(
    block,
    city: 'tokyo',
    display_name: tokyo.fetch(:display_name),
    bundle_id: tokyo.fetch(:bundle_id),
    app_icon_name: tokyo.fetch(:app_icon_name),
    exclude_plist: false
  )
  text = text.sub(block, updated)
end

expected_names = CITIES.keys.product(BUILD_KINDS).map { |city, kind| "#{kind}-#{city}" }
core_ids = PROJECT_IDS.values + RUNNER_IDS.values
core_present = core_ids.select { |id| config_block_present?(text, id) }
if core_present.any? && core_present.length != core_ids.length
  abort 'Xcode project/Runner flavor configurations are partially generated'
end

if core_present.empty?
  generated_blocks = []
  CITIES.each do |city, config|
    BUILD_KINDS.each do |kind|
      project_base = extract_config_block(text, BASE_PROJECT_CONFIGS.fetch(kind))
      project_block = rename_config_block(
        project_base,
        old_id: BASE_PROJECT_CONFIGS.fetch(kind),
        new_id: PROJECT_IDS.fetch([kind, city]),
        old_name: kind,
        new_name: "#{kind}-#{city}"
      )
      generated_blocks << project_block

      runner_base = extract_config_block(text, BASE_RUNNER_CONFIGS.fetch(kind))
      runner_block = rename_config_block(
        runner_base,
        old_id: BASE_RUNNER_CONFIGS.fetch(kind),
        new_id: RUNNER_IDS.fetch([kind, city]),
        old_name: kind,
        new_name: "#{kind}-#{city}"
      )
      runner_block = ensure_runner_city_settings(
        runner_block,
        city: city,
        display_name: config.fetch(:display_name),
        bundle_id: config.fetch(:bundle_id),
        app_icon_name: config.fetch(:app_icon_name),
        exclude_plist: config.fetch(:exclude_tokyo_firebase_plist)
      )
      generated_blocks << runner_block
    end
  end

  marker = "/* End XCBuildConfiguration section */"
  abort 'XCBuildConfiguration end marker not found' unless text.include?(marker)
  text = text.sub(marker, "#{generated_blocks.join("\n")}\n#{marker}")
end

# Existing generated Runner configurations are reconciled too. This makes icon,
# bundle-ID and Firebase isolation changes deterministic instead of requiring
# manual pbxproj edits.
CITIES.each do |city, config|
  BUILD_KINDS.each do |kind|
    block = extract_config_block(text, RUNNER_IDS.fetch([kind, city]))
    updated = ensure_runner_city_settings(
      block,
      city: city,
      display_name: config.fetch(:display_name),
      bundle_id: config.fetch(:bundle_id),
      app_icon_name: config.fetch(:app_icon_name),
      exclude_plist: config.fetch(:exclude_tokyo_firebase_plist)
    )
    text = text.sub(block, updated)
  end
end

# CocoaPods inspects every target for every project configuration. RunnerTests
# therefore needs the same flavored configuration names as Runner; otherwise
# CocoaPods sees a mixture of Swift 5.0 and an undefined Swift version.
test_ids = TEST_IDS.values
test_present = test_ids.select { |id| config_block_present?(text, id) }
if test_present.any? && test_present.length != test_ids.length
  abort 'RunnerTests flavor configurations are partially generated'
end

if test_present.empty?
  generated_test_blocks = []
  CITIES.each do |city, config|
    BUILD_KINDS.each do |kind|
      test_base = extract_config_block(text, BASE_TEST_CONFIGS.fetch(kind))
      test_block = rename_config_block(
        test_base,
        old_id: BASE_TEST_CONFIGS.fetch(kind),
        new_id: TEST_IDS.fetch([kind, city]),
        old_name: kind,
        new_name: "#{kind}-#{city}"
      )
      test_block = ensure_test_city_settings(
        test_block,
        bundle_id: config.fetch(:bundle_id)
      )
      generated_test_blocks << test_block
    end
  end
  marker = "/* End XCBuildConfiguration section */"
  text = text.sub(marker, "#{generated_test_blocks.join("\n")}\n#{marker}")
else
  CITIES.each do |city, config|
    BUILD_KINDS.each do |kind|
      block = extract_config_block(text, TEST_IDS.fetch([kind, city]))
      updated = ensure_test_city_settings(block, bundle_id: config.fetch(:bundle_id))
      text = text.sub(block, updated)
    end
  end
end

project_entries = []
runner_entries = []
test_entries = []
CITIES.keys.each do |city|
  BUILD_KINDS.each do |kind|
    name = "#{kind}-#{city}"
    project_entries << "\t\t\t\t#{PROJECT_IDS.fetch([kind, city])} /* #{name} */,\n"
    runner_entries << "\t\t\t\t#{RUNNER_IDS.fetch([kind, city])} /* #{name} */,\n"
    test_entries << "\t\t\t\t#{TEST_IDS.fetch([kind, city])} /* #{name} */,\n"
  end
end

text = append_configuration_entries(
  text,
  '97C146E91CF9000F007C117D',
  "\t\t\t\t97C147031CF9000F007C117D /* Debug */,\n",
  project_entries
)
text = append_configuration_entries(
  text,
  '97C147051CF9000F007C117D',
  "\t\t\t\t97C147061CF9000F007C117D /* Debug */,\n",
  runner_entries
)
text = append_configuration_entries(
  text,
  '331C8087294A63A400263BE5',
  "\t\t\t\t331C8088294A63A400263BE5 /* Debug */,\n",
  test_entries
)

expected_names.each do |name|
  abort "Generated project is missing #{name}" unless text.include?("name = #{name};")
end

CITIES.each do |city, config|
  BUILD_KINDS.each do |kind|
    runner_block = extract_config_block(text, RUNNER_IDS.fetch([kind, city]))
    abort "#{kind}-#{city} has wrong bundle identifier" unless runner_block.include?(
      "PRODUCT_BUNDLE_IDENTIFIER = #{config.fetch(:bundle_id)};"
    )
    abort "#{kind}-#{city} has wrong APP_CITY" unless runner_block.include?("APP_CITY = #{city};")
    abort "#{kind}-#{city} has wrong display name" unless runner_block.include?(
      "APP_DISPLAY_NAME = \"#{config.fetch(:display_name)}\";"
    )
    abort "#{kind}-#{city} has wrong app icon set" unless runner_block.include?(
      "ASSETCATALOG_COMPILER_APPICON_NAME = #{config.fetch(:app_icon_name)};"
    )
    if config.fetch(:exclude_tokyo_firebase_plist)
      abort "#{kind}-#{city} does not exclude Tokyo Firebase plist" unless runner_block.include?(
        'EXCLUDED_SOURCE_FILE_NAMES = "GoogleService-Info.plist";'
      )
    end

    test_block = extract_config_block(text, TEST_IDS.fetch([kind, city]))
    abort "RunnerTests #{kind}-#{city} has wrong bundle identifier" unless test_block.include?(
      "PRODUCT_BUNDLE_IDENTIFIER = #{config.fetch(:bundle_id)}.RunnerTests;"
    )
    abort "RunnerTests #{kind}-#{city} has wrong Swift version" unless test_block.include?(
      'SWIFT_VERSION = 5.0;'
    )
  end
end

if CHECK_ONLY
  abort 'ios/Runner.xcodeproj/project.pbxproj is not generated; run scripts/configure_ios_flavors.rb' if text != original
  puts 'iOS flavor project is up to date.'
else
  if text == original
    puts 'iOS flavor project already up to date.'
  else
    File.write(PROJECT_PATH, text, encoding: 'UTF-8')
    puts 'Updated ios/Runner.xcodeproj/project.pbxproj.'
  end
end
