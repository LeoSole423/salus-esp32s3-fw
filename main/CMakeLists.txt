idf_component_register(SRCS "salus_main.c"
    PRIV_REQUIRES salus_board salus_protocol salus_imu esp_system esp_psram
                  esp_driver_usb_serial_jtag esp_timer log)
