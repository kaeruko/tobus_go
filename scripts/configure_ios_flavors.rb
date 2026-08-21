#!/usr/bin/env ruby
# frozen_string_literal: true

# Deterministically expands the stock Runner Xcode configurations into
# Debug/Profile/Release configurations for tokyo, nagoya and sendai.
#
# The script is intentionally fail-fast: it only knows the exact configuration
# IDs in this repository and refuses a partially generated or unexpected state.

PROJECT_PATH = File.expand_path('../ios/Runner.xcodeproj/project.pbxproj', __dir__)
CHECK_ONLY = ARGV == ['--check']
unless ARGV.empty? || CHECK_ONLY
  abort 'usage: ruby scripts/configure_ios_flavors.rb [--check]'
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

CITIES = {
  'tokyo' => {
    bundle_id: 'jp.cloxs.toeigo',
    display_name: '都営でGO',
    exclude_tokyo_firebase_plist: false
  },
  'nagoya' => {
    bundle_id: 'jp.cloxs.nagoyago',
    display_name: '名古屋でGO',
    exclude_tokyo_firebase_plist: true
  },
  'sendai' => {
    bundle_id: 'jp.cloxs.sendaigo',
    display_name: '仙台でGO',
    exclude_tokyo_firebase_plist: true
  }
}.freeze

BUILD_KINDS = %w[Debug Release Profile].freeze

PROJECT_IDS = {}
RUNNER_IDS = {}
CITIES.keys.each_with_index do |city, city_index|
  BUILD_KINDS.each_with_index do |kind, kind_index|
    ordinal = city_index * BUILD_KINDS.length + kind_index + 1
    PROJECT_IDS[[kind, city]] = format('A1000000000000000000%04X', ordinal)
    RUNNER_IDS[[kind, city]] = format('B1000000000000000000%04X', ordinal)
  end
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

def ensure_runner_city_settings(block, city:, display_name:, bundle_id:, exclude_plist:)
  result = block
  anchor = "\t\t\t\tASSETCATALOG_COMPILER_APPICON_NAME = AppIcon;\n"
  abort 'Runner configuration is missing AppIcon anchor' unless result.include?(anchor)

  if result.include?('APP_CITY = ')
    result = result.sub(/\t\t\t\tAPP_CITY = [^;]+;/,
                        "\t\t\t\tAPP_CITY = #{city};")
  else
    result = result.sub(anchor, "#{anchor}\t\t\t\tAPP_CITY = #{city};\n")
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
BASE_RUNNER_CONFIGS.each do |kind, id|
  block = extract_config_block(text, id)
  updated = ensure_runner_city_settings(
    block,
    city: 'tokyo',
    display_name: CITIES.fetch('tokyo').fetch(:display_name),
    bundle_id: CITIES.fetch('tokyo').fetch(:bundle_id),
    exclude_plist: false
  )
  text = text.sub(block, updated)
end

expected_names = CITIES.keys.product(BUILD_KINDS).map { |city, kind| "#{kind}-#{city}" }
present_names = expected_names.select { |name| text.include?("name = #{name};") }
if present_names.any? && present_names.length != expected_names.length
  abort "Xcode flavor configurations are partially generated: #{present_names.sort.join(', ')}"
end

if present_names.empty?
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
        exclude_plist: config.fetch(:exclude_tokyo_firebase_plist)
      )
      generated_blocks << runner_block
    end
  end

  marker = "/* End XCBuildConfiguration section */"
  abort 'XCBuildConfiguration end marker not found' unless text.include?(marker)
  text = text.sub(marker, "#{generated_blocks.join("\n")}\n#{marker}")
end

project_entries = []
runner_entries = []
CITIES.keys.each do |city|
  BUILD_KINDS.each do |kind|
    name = "#{kind}-#{city}"
    project_entries << "\t\t\t\t#{PROJECT_IDS.fetch([kind, city])} /* #{name} */,\n"
    runner_entries << "\t\t\t\t#{RUNNER_IDS.fetch([kind, city])} /* #{name} */,\n"
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

expected_names.each do |name|
  abort "Generated project is missing #{name}" unless text.include?("name = #{name};")
end

CITIES.each do |city, config|
  BUILD_KINDS.each do |kind|
    block = extract_config_block(text, RUNNER_IDS.fetch([kind, city]))
    abort "#{kind}-#{city} has wrong bundle identifier" unless block.include?(
      "PRODUCT_BUNDLE_IDENTIFIER = #{config.fetch(:bundle_id)};"
    )
    abort "#{kind}-#{city} has wrong APP_CITY" unless block.include?("APP_CITY = #{city};")
    abort "#{kind}-#{city} has wrong display name" unless block.include?(
      "APP_DISPLAY_NAME = \"#{config.fetch(:display_name)}\";"
    )
    if config.fetch(:exclude_tokyo_firebase_plist)
      abort "#{kind}-#{city} does not exclude Tokyo Firebase plist" unless block.include?(
        'EXCLUDED_SOURCE_FILE_NAMES = "GoogleService-Info.plist";'
      )
    end
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
