#include "INA219.h"

#define INA219_CALIBRATION_VALUE 4096
#define INA219_CURRENT_LSB       0.1f

static HAL_StatusTypeDef WriteRegister(
    I2C_HandleTypeDef *hi2c,
    uint8_t reg,
    uint16_t value)
{
    uint8_t data[2];

    data[0] = value >> 8;
    data[1] = value & 0xFF;

    return HAL_I2C_Mem_Write(
        hi2c,
        INA219_ADDRESS,
        reg,
        I2C_MEMADD_SIZE_8BIT,
        data,
        2,
        100
    );
}

static HAL_StatusTypeDef ReadRegister(
    I2C_HandleTypeDef *hi2c,
    uint8_t reg,
    uint16_t *value)
{
    uint8_t data[2];

    HAL_StatusTypeDef status = HAL_I2C_Mem_Read(
        hi2c,
        INA219_ADDRESS,
        reg,
        I2C_MEMADD_SIZE_8BIT,
        data,
        2,
        100
    );

    if (status != HAL_OK)
        return status;

    *value = ((uint16_t)data[0] << 8) | data[1];

    return HAL_OK;
}

HAL_StatusTypeDef INA219_Init(I2C_HandleTypeDef *hi2c)
{
    // Reset sensor
    if (WriteRegister(hi2c, INA219_REG_CONFIG, 0x8000) != HAL_OK)
        return HAL_ERROR;

    HAL_Delay(2);

    // Configure sensor:
    // 32V bus range
    // 320mV shunt range
    // 12-bit ADC
    // Continuous measurement
    if (WriteRegister(hi2c, INA219_REG_CONFIG, 0x399F) != HAL_OK)
        return HAL_ERROR;

    // Set calibration
    if (WriteRegister(
        hi2c,
        INA219_REG_CALIB,
        INA219_CALIBRATION_VALUE
    ) != HAL_OK)
        return HAL_ERROR;

    return HAL_OK;
}

HAL_StatusTypeDef INA219_ReadCurrent(
    I2C_HandleTypeDef *hi2c,
    float *current_mA)
{
    uint16_t raw;

    if (ReadRegister(
        hi2c,
        INA219_REG_CURRENT,
        &raw
    ) != HAL_OK)
        return HAL_ERROR;

    *current_mA = (int16_t)raw * INA219_CURRENT_LSB;

    return HAL_OK;
}

HAL_StatusTypeDef INA219_ReadBusVoltage(
    I2C_HandleTypeDef *hi2c,
    float *voltage_V)
{
    uint16_t raw;

    if (ReadRegister(
        hi2c,
        INA219_REG_BUS,
        &raw
    ) != HAL_OK)
        return HAL_ERROR;

    *voltage_V = (raw >> 3) * 0.004f;

    return HAL_OK;
}
