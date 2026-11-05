CC ?= gcc
CXX ?= g++
LVGL ?= ../../test_support/lvgl-9.4.0
CPPFLAGS += -I. -I$(LVGL) -DLV_CONF_INCLUDE_SIMPLE -D_DEFAULT_SOURCE
CFLAGS ?= -O2 -std=c99 -Wall -Wextra -ffunction-sections -fdata-sections
BUILD ?= build
TARGET ?= cabinet_dashboard
APP_OBJECT ?= dashboard
GC_SECTIONS ?= -Wl,--gc-sections
SOURCES := $(shell find $(LVGL)/src -name '*.c' ! -name '._*') $(wildcard fonts/*.c)
OBJECTS := $(patsubst %.c,$(BUILD)/%.o,$(SOURCES)) $(BUILD)/$(APP_OBJECT).o
all: $(TARGET) native/libedge_mmio.so
$(TARGET): $(OBJECTS)
	$(CC) $(GC_SECTIONS) -o $@ $^ -lm -pthread
$(BUILD)/%.o: %.c lv_conf.h fonts/ui_fonts.h parameter_view.h parameter_wire.h
	@mkdir -p $(dir $@)
	$(CC) $(CPPFLAGS) $(CFLAGS) -c $< -o $@
$(BUILD)/$(LVGL)/src/drivers/opengles/assets/lv_opengles_shader.o: $(LVGL)/src/drivers/opengles/assets/lv_opengles_shader.c lv_conf.h
	@mkdir -p $(dir $@)
	$(CXX) -x c++ $(CPPFLAGS) $(filter-out -std=c99,$(CFLAGS)) -std=c++11 -c $< -o $@
$(BUILD)/$(LVGL)/src/libs/gltf/gltf_view/assets/lv_gltf_view_shader.o: $(LVGL)/src/libs/gltf/gltf_view/assets/lv_gltf_view_shader.c lv_conf.h
	@mkdir -p $(dir $@)
	$(CXX) -x c++ $(CPPFLAGS) $(filter-out -std=c99,$(CFLAGS)) -std=c++11 -c $< -o $@
$(BUILD)/capture_dashboard.o: dashboard.c capture_view.h lv_conf.h fonts/ui_fonts.h
	@mkdir -p $(dir $@)
	$(CC) $(CPPFLAGS) $(CFLAGS) -DCABINET_RECORDING -c $< -o $@
native/libedge_mmio.so: native/mmio.c
	$(CC) -O2 -Wall -Wextra -Werror -shared -fPIC -o $@ $<
