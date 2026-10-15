idf_build_get_property(bosch_dir SALUS_BOSCH_DIR)
idf_component_register(SRCS "${bosch_dir}/bmi08a.c" "${bosch_dir}/bmi08g.c"
                           "${bosch_dir}/bmi08xa.c"
                       INCLUDE_DIRS "${bosch_dir}")
