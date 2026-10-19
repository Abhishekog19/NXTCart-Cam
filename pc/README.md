# PC product verification

Run only this workspace on the PC. It receives transaction requests and JPEG
camera frames through ROS 2, follows the product to rest, compares its crops
against the scanned SKU, and returns a verdict. Cart quantities, price,
Arduino, QR capture and the display belong to `../Cart-RestCode/` on the Pi.

See [`SYSTEM_SETUP.md`](../SYSTEM_SETUP.md) for the complete setup and test plan.
After building and capturing references:

```bash
bash pc/run_verifier.sh backend:=local
```

Switch to `backend:=ai` with an explicitly chosen image-capable provider/model
and a PC environment API key. The Pi contract is the same for either choice.
