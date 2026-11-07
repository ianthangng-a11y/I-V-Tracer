#ifndef INA219_H
#define INA219_H

#include "stm32f7xx_hal.h"

#define INA219_ADDRESS       (0x40 << 1)

#define INA219_REG_CONFIG    0x00
#define INA219_REG_SHUNT     0x01
#define INA219_REG_BUS       0x02
#define INA219_REG_CURRENT   0x04
#define INA219_REG_CALIB     0x05

HAL_StatusTypeDef INA219_Init(I2C_HandleTypeDef *hi2c);

HAL_StatusTypeDef INA219_ReadCurrent(
    I2C_HandleTypeDef *hi2c,
    float *current_mA
);

HAL_StatusTypeDef INA219_ReadBusVoltage(
    I2C_HandleTypeDef *hi2c,
    float *voltage_V
);

#endif
