/**
 * Hubble / Zephyr RTOS Environmental Sensor Decoder for NibiaaNet
 * 
 * Zephyr Firmware Payload Layout (13 bytes total):
 *   int16_t  temp     = 2000 + (sys_rand32_get() % 1000);   // buf[0..1]  (LE, 20.00 - 29.99 °C)
 *   uint16_t humidity = 4000 + (sys_rand32_get() % 4000);   // buf[2..3]  (LE, 40.00 - 79.99 %)
 *   uint32_t pressure = 100000 + (sys_rand32_get() % 2000); // buf[4..7]  (LE, 100000 - 101999 Pa)
 *   uint16_t batt_mv  = 3500 + (sys_rand32_get() % 500);    // buf[8..9]  (LE, 3500 - 3999 mV)
 *   uint8_t  flags    = 0x01;                               // buf[10]    (bit0 = alive)
 *   uint16_t _seq     = seq++;                              // buf[11..12](LE, packet sequence counter)
 */

function base64ToBytes(b64) {
  var chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
  var lookup = {};
  for (var i = 0; i < chars.length; i++) lookup[chars.charAt(i)] = i;
  var clean = b64.replace(/[^A-Za-z0-9+/]/g, "");
  var len = clean.length;
  var byteLen = Math.floor((len * 3) / 4);
  var bytes = [];
  for (var i = 0; i < len; i += 4) {
    var b0 = lookup[clean.charAt(i)] || 0;
    var b1 = lookup[clean.charAt(i + 1)] || 0;
    var b2 = lookup[clean.charAt(i + 2)] || 0;
    var b3 = lookup[clean.charAt(i + 3)] || 0;
    bytes.push((b0 << 2) | (b1 >> 4));
    if (i + 2 < len && clean.charAt(i + 2) !== "=") bytes.push(((b1 & 15) << 4) | (b2 >> 2));
    if (i + 3 < len && clean.charAt(i + 3) !== "=") bytes.push(((b2 & 3) << 6) | b3);
  }
  return bytes;
}

function hexToBytes(hex) {
  var clean = hex.replace(/[^0-9a-fA-F]/g, "");
  var bytes = [];
  for (var i = 0; i < clean.length; i += 2) {
    bytes.push(parseInt(clean.substr(i, 2), 16));
  }
  return bytes;
}

function isJsonBytes(bytes) {
  if (!bytes || bytes.length === 0) return false;
  var first = bytes[0];
  return first === 123 || first === 91 || first === 32 || first === 10 || first === 13;
}

function extractPayloadBytes(input) {
  // 1. Check formatted hex from device or input
  var hexCandidate = (input && input.device && input.device.payload_hex) || (input && input.payload_hex);
  if (hexCandidate && typeof hexCandidate === "string") {
    var hb = hexToBytes(hexCandidate);
    if (hb.length >= 13) return hb;
  }

  // 2. Check base64 payload from device or input
  var b64Candidate = (input && input.device && typeof input.device.payload === "string" ? input.device.payload : null) ||
                     (input && typeof input.payload === "string" && !input.payload.startsWith("{") ? input.payload : null) ||
                     (input && typeof input.base64 === "string" && !input.base64.startsWith("{") ? input.base64 : null);
  if (b64Candidate && typeof b64Candidate === "string") {
    var bb = base64ToBytes(b64Candidate);
    if (bb.length >= 13) return bb;
  }

  // 3. Raw payload bytes (only if binary, not serialized JSON)
  if (input && Array.isArray(input.bytes) && input.bytes.length >= 13 && !isJsonBytes(input.bytes)) {
    return input.bytes;
  }

  return null;
}

function decodeSensorData(bytes) {
  if (!bytes || bytes.length < 13) return {};

  // Zephyr Little-Endian layout:
  // buf[0..1]: temp (int16_t, little-endian, scaled * 100)
  var tRaw = bytes[0] | (bytes[1] << 8);
  if (tRaw >= 0x8000) tRaw -= 0x10000;
  var temp_le = parseFloat((tRaw / 100.0).toFixed(2));

  // buf[2..3]: humidity (uint16_t, little-endian, scaled * 100)
  var hum_le = parseFloat(((bytes[2] | (bytes[3] << 8)) / 100.0).toFixed(2));

  // buf[4..7]: pressure (uint32_t, little-endian, in Pa)
  var press_le = (bytes[4] | (bytes[5] << 8) | (bytes[6] << 16) | ((bytes[7] << 24) >>> 0)) >>> 0;

  // buf[8..9]: batt_mv (uint16_t, little-endian, in mV)
  var batt_le = bytes[8] | (bytes[9] << 8);

  // buf[10]: flags (uint8_t, bit0=alive)
  var flags_le = bytes[10];

  // buf[11..12]: sequence (uint16_t, little-endian)
  var seq_le = bytes[11] | (bytes[12] << 8);

  // Validate if pressure and humidity match typical environmental ranges
  if (press_le >= 50000 && press_le <= 150000 && hum_le >= 0 && hum_le <= 100) {
    return {
      temperature: temp_le,
      humidity: hum_le,
      pressure: press_le,
      pressure_hpa: parseFloat((press_le / 100.0).toFixed(2)),
      battery: batt_le,
      battery_voltage: batt_le,
      flags: flags_le,
      sequence: seq_le
    };
  }

  // Fallback for alternate / BE layout (e.g. 000e1c31200a39001618180938)
  var seq_be = (bytes[0] << 8) | bytes[1];
  var hum_be = parseFloat((((bytes[9] << 8) | bytes[10]) / 100.0).toFixed(2));
  var tBe = (bytes[11] << 8) | bytes[12];
  if (tBe >= 0x8000) tBe -= 0x10000;
  var temp_be = parseFloat((tBe / 100.0).toFixed(2));

  return {
    temperature: (temp_le >= -40 && temp_le <= 85) ? temp_le : temp_be,
    humidity: (hum_le >= 0 && hum_le <= 100) ? hum_le : hum_be,
    pressure: press_le,
    pressure_hpa: parseFloat((press_le / 100.0).toFixed(2)),
    battery: (batt_le >= 2000 && batt_le <= 5000) ? batt_le : 3700,
    battery_voltage: (batt_le >= 2000 && batt_le <= 5000) ? batt_le : 3700,
    flags: flags_le,
    sequence: (seq_le > 0 && seq_le < 65000) ? seq_le : seq_be
  };
}

function transform(input) {
  return decode(input);
}

function decode(input) {
  var loc = input.location || {};
  var dev = input.device || {};

  var rawPayload = (typeof dev.payload === "string" ? dev.payload : "") || 
                   (typeof input.payload === "string" ? input.payload : "") || 
                   (typeof input.payload_raw === "string" ? input.payload_raw : "");

  var rawPayloadHex = (typeof dev.payload_hex === "string" ? dev.payload_hex : "") || 
                      (typeof input.payload_hex === "string" ? input.payload_hex : "");

  var deviceName = dev.name || input.device_name || input.deviceName || "xiao-69s-MG24";
  var network_type = input.network_type || dev.network_type || "TERRESTRIAL";

  var bytes = extractPayloadBytes(input);
  var sensor = decodeSensorData(bytes);

  var dataOut = Object.assign({}, sensor, {
    payload: rawPayload,
    payload_hex: rawPayloadHex,
    latitude: input.latitude !== undefined ? input.latitude : loc.latitude,
    longitude: input.longitude !== undefined ? input.longitude : loc.longitude,
    altitude: input.altitude !== undefined ? input.altitude : loc.altitude,
    horizontal_accuracy: input.horizontal_accuracy !== undefined ? input.horizontal_accuracy : (loc.horizontal_accuracy || loc.accuracy),
    rssi: input.rssi !== undefined ? input.rssi : dev.rssi,
    sequence_number: sensor.sequence !== undefined ? sensor.sequence : (input.sequence_number !== undefined ? input.sequence_number : (dev.sequence_number || dev.seq)),
    counter: input.counter !== undefined ? input.counter : dev.counter,
    network_type: network_type,
    location: loc,
    device: dev
  });

  return {
    deviceName: deviceName,
    deviceType: (network_type === "TERRESTRIAL" || network_type === "BLE") ? "BLE" : "NTN",
    data: dataOut,
    units: {
      temperature: "°C",
      humidity: "%",
      pressure: "Pa",
      pressure_hpa: "hPa",
      battery: "mV",
      battery_voltage: "mV",
      altitude: "m",
      horizontal_accuracy: "m",
      rssi: "dBm"
    }
  };
}
