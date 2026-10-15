# The following lines of boilerplate have to be in your project's
# CMakeLists in this exact order for cmake to work correctly
cmake_minimum_required(VERSION 3.22)

set(IDF_TARGET "esp32s3" CACHE STRING "SALUS PCB v3 target")
include($ENV{IDF_PATH}/tools/cmake/project.cmake)
# "Trim" the build. Include the minimal set of components, main, and anything it depends on.
idf_build_set_property(MINIMAL_BUILD ON)
# Dependency is pinned and checksum-verified, never vendored into source.
execute_process(COMMAND python3 "${CMAKE_SOURCE_DIR}/tools/fetch_bosch.py"
    "${CMAKE_BINARY_DIR}/bosch" RESULT_VARIABLE SALUS_BOSCH_RESULT)
if(NOT SALUS_BOSCH_RESULT EQUAL 0)
    message(FATAL_ERROR "Could not prepare pinned Bosch BMI08x API")
endif()
idf_build_set_property(SALUS_BOSCH_DIR "${CMAKE_BINARY_DIR}/bosch")
project(salus_esp32s3_fw)

include($ENV{IDF_PATH}/tools/cmake/version.cmake)
set(SALUS_IDF_VERSION "${IDF_VERSION_MAJOR}.${IDF_VERSION_MINOR}.${IDF_VERSION_PATCH}")
if(NOT SALUS_IDF_VERSION VERSION_EQUAL "6.0.2")
    message(FATAL_ERROR "SALUS skeleton requires ESP-IDF 6.0.2; found ${SALUS_IDF_VERSION}")
endif()
