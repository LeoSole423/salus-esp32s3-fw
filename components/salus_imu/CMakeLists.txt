idf_component_register(SRCS "salus_imu.c" "salus_imu_core.c"
    INCLUDE_DIRS "include" REQUIRES bmi08x esp_common
    PRIV_REQUIRES salus_protocol
                  salus_board esp_driver_spi esp_driver_gpio esp_timer esp_rom freertos)
