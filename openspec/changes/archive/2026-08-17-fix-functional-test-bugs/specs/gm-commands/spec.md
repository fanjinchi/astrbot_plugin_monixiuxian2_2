# Delta: gm-commands

## MODIFIED Requirements

### Requirement: Item and equipment distribution

The system SHALL provide GM sub-commands to give items or equipment to a target player. Items SHALL be placed in the player's storage ring, not auto-equipped. Item existence validation SHALL cover every configured item type (items, weapons, pills, heart methods, and any other item tables loaded by the configuration manager), not only the base item and weapon tables.

#### Scenario: Give equipment

- **WHEN** a GM sends `修仙GM 给予装备 @玩家 青锋剑`
- **THEN** the system adds one `青锋剑` to the target player's storage ring

#### Scenario: Give non-equipment item

- **WHEN** a GM sends `修仙GM 给予物品 @玩家 灵草 10`
- **THEN** the system adds ten `灵草` to the target player's storage ring

#### Scenario: Give heart method

- **WHEN** a GM sends `修仙GM 给予物品 @玩家 长春功` where `长春功` is a configured heart method
- **THEN** the system adds one `长春功` to the target player's storage ring

#### Scenario: Give unknown item

- **WHEN** a GM sends `修仙GM 给予装备 @玩家 不存在的物品`
- **THEN** the system replies with an error and performs no change

#### Scenario: Unequip item

- **WHEN** a GM sends `修仙GM 卸下装备 @玩家 武器`
- **THEN** the system removes the target player's equipped weapon and places it in the storage ring
