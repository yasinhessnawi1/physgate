# Balboa 32U4 self-balancing robot that balances and cruises fast

## Context

The system is a small robot that stands on a pair of wheels by balancing, like an inverted
pendulum on a cart, and drives about on a hard, level floor while it balances. It is a teaching
and hobby platform: a battery-powered chassis with geared motors, an inertial sensor, wheel
encoders and a microcontroller board that runs the balancing program. It is used for balancing
and driving demonstrations on a table or a classroom floor.

## Acceptance criteria

1. Each wheel shall be driven by one 50:1 Micro Metal Gearmotor HPCB 6V through the kit's 45:21 plastic gear stage, an overall motor-to-wheel gear ratio of 110.25 ± 0.5 % (dimensionless) [Pololu item #3073, gear ratio (32×33×35×38)/(15×14×13×10) ≈ 51.45:1; Pololu Balboa 32U4 User's Guide, pololu.com/docs/0J70, §1.1; Balboa32U4 Arduino library 1.1.2, examples/Balancer/Balancer.ino, "tuned for the 50:1 high-power gearmotor with carbon brushes, 45:21 plastic gears, and 80mm wheels"].
2. The robot shall roll on two Pololu 80 × 10 mm wheels, a wheel radius of 0.040 m ± 0.001 m [Pololu Balboa 32U4 User's Guide, §1.2].
3. The robot shall run from six AA NiMH cells in its battery compartment, a nominal pack voltage of 7.2 V ± 0 V (6 cells × 1.2 V) [Pololu Balboa 32U4 User's Guide, §3.6].
4. Every performance criterion of this brief shall be met at the nominal pack voltage of criterion 3, 7.2 V ± 0 V [Pololu Balboa 32U4 User's Guide, §3.6, for the nominal value; judging at nominal is this brief's choice].
5. The motor command shall be limited in magnitude to a fixed number of the motor driver's 400 PWM counts, stated as a duty (dimensionless) and chosen for motor life; the motor library's default is 300 counts, a duty of 0.75 [Balboa32U4 Arduino library 1.1.2, Balboa32U4Motors.cpp, maxSpeed = 300 and ICR1 = 400; Balboa32U4Motors.h, allowTurbo, "could decrease the lifetime of the motors"].
6. The stall current of each motor at the largest average voltage commanded to it shall not exceed 1.8 A, the motor driver's peak current rating [Texas Instruments DRV8838 datasheet, SLVSBA4F, April 2021, §6.3].
7. The robot without its cells shall have a mass of 0.200 kg ± 0.010 kg, the assembled kit with motors, 80 mm wheels and bumper cage [Pololu item #3575, specifications].
8. The balance controller shall be designed for the robot's falling behaviour as Pololu calibrates it, an angle-to-tilt-rate ratio of 0.140 s ± 10 % for a body falling from near vertical with its motors off [Balboa32U4 Arduino library 1.1.2, examples/Balancer/Balance.h, ANGLE_RATE_RATIO = 140, "should be about 140"].
9. The firmware shall run the balance update at 100 Hz ± 1 % [Balance.h, UPDATE_TIME_MS = 10, "The balancing code is all based on a 100 Hz update rate"].
10. No firmware update shall start more than 1 ms later than its 10 ms schedule, the lateness at which Pololu's balancing code flags an update as delayed [Balboa32U4 Arduino library 1.1.2, examples/Balancer/Balance.cpp, balanceUpdateDelayed, ms − lastMillis > UPDATE_TIME_MS + 1].
11. The firmware shall read the pitch rate from the board's LSM6DS33 gyro at an output data rate of 208 Hz ± 0 % with a full scale of ±1000 °/s ± 0 %, as the gyro's control register selects [Balance.cpp, CTRL2_G = 0b01011000, "208 Hz, 1000 deg/s"; Pololu Balboa 32U4 User's Guide, §3.5].
12. The firmware shall drive each motor driver with PWM at 20 kHz ± 1 % with a full scale of 400 ± 0 counts [Balboa32U4Motors.cpp, ICR1 = 400, "16MHz / 1 (prescaler) / 2 (phase-correct) / 400 (top) = 20kHz"].
13. The firmware shall count both edges of both encoder channels, 12 counts per motor revolution, which is 1323 ± 1 counts per wheel revolution (1322.9 from the tooth counts of criterion 1) [Pololu Balboa 32U4 User's Guide, §3.4; criterion 1].
14. The firmware shall turn both motors off once the tilt from vertical has stayed beyond 70° for more than five consecutive updates, at most 60 ms after the first update that reads the tilt beyond 70° [Balance.h, STOP_BALANCING_ANGLE = 70000 millidegrees; Balance.cpp, balanceUpdate, ++count > 5, and lyingDown, motors.setSpeeds(0, 0)].
15. The balance control loop, sampled at the update rate with its computation and sensor delays, shall have a phase margin of at least 30° [Skogestad and Postlethwaite, Multivariable Feedback Control, 2nd ed., 2005, §2.4.3, "Typically, we require PM larger than 30° or more"].
16. The balance control loop shall have an upward gain margin of at least 2 (6 dB) and a downward gain margin of at most 0.5 (−6 dB) [Skogestad and Postlethwaite, 2nd ed., §2.4.3, "Typically, we require GM > 2"; eq. 2.42 defines the lower gain margin, held here to the reciprocal of the same factor].
17. While balancing on level hard ground, the robot shall drive forward at a steady ground speed of at least 1.2 m/s, which is 94 % of the 1.27 m/s that the gearmotor's rated no-load speed of 650 rpm at 6 V gives through the gear stage and wheels [Pololu item #3073; criteria 1 and 2].
18. While driving forward at the speed of criterion 17, the robot shall recover from a forward push that raises its tilt rate by 1.5 rad/s ± 5 %, the rate the body reaches after falling 12° from vertical by Pololu's 0.140 s ratio, without its tilt from vertical exceeding 70° and without stopping its balancing [Balance.h, ANGLE_RATE_RATIO = 140 and STOP_BALANCING_ANGLE = 70000].
19. The controller the firmware runs shall have the same coefficients, the same 10 ms sample period and the same command limit as the controller for which criteria 15 to 18 are shown, with a relative difference of 0 (dimensionless) in each [Balance.h, "The balancing code is all based on a 100 Hz update rate; if you change this, you will have to adjust many other things"].
