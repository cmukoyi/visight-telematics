# PinPlot

Welcome to the **PinPlot Project**!

This repository is the home of PinPlot, where we’re building and experimenting with code, scripts, and workflows.  
Feel free to explore, contribute, and help improve the project.

## Getting Started
- Clone the repository
- Follow instructions in the documentation to run or test components

## Contributing
Pull requests are welcome. For major changes, please open an issue first to discuss what you’d like to change.

---

Enjoy working with PinPlot!

SELECT
  bt.imei,
  bt.device_name,
  bt.tag_type,
  tp.name AS package,
  tp.validity_days,
  bt.activation_date,
  bt.expiry_date,
  CASE
    WHEN bt.package_id IS NULL            THEN 'no package'
    WHEN bt.expiry_date IS NULL           THEN 'NEW'
    WHEN bt.expiry_date < now()           THEN 'EXPIRED'
    WHEN bt.expiry_date < now() + interval '7 days' THEN 'expiring soon'
    ELSE 'active'
  END AS status
FROM ble_tags bt
LEFT JOIN tag_packages tp ON tp.id = bt.package_id
ORDER BY bt.expiry_date ASC NULLS LAST;