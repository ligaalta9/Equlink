#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
// Tambahkan library PZEM004Tv30 untuk PZEM-004T sesuai wiring Anda.
// Sesuaikan SSID, password, MQTT host, username, password, dan pin relay.
const char* WIFI_SSID="YOUR_WIFI"; const char* WIFI_PASS="YOUR_WIFI_PASSWORD";
const char* MQTT_HOST="YOUR_EMQX_HOST"; const int MQTT_PORT=8883; const char* MQTT_USER="YOUR_MQTT_USERNAME"; const char* MQTT_PASS="YOUR_MQTT_PASSWORD";
WiFiClientSecure net; PubSubClient mqtt(net);
const char* T_R1="equilink/room1/sensor"; const char* T_R2="equilink/room2/sensor"; const char* T_W="equilink/water/sensor"; const char* T_R1R="equilink/room1/relay"; const char* T_R2R="equilink/room2/relay"; const char* T_P="equilink/water/pump";
void connectWiFi(){WiFi.begin(WIFI_SSID,WIFI_PASS);while(WiFi.status()!=WL_CONNECTED)delay(500);}void callback(char* topic,byte* payload,unsigned int len){StaticJsonDocument<256>d;deserializeJson(d,payload,len);String t=topic;if(t==T_R1R||t==T_R2R){String dev=d["device"]|"";bool s=d["state"]|false;/* digitalWrite pin sesuai device */}if(t==T_P){bool s=d["state"]|false;/* kontrol pompa */}}
void reconnect(){while(!mqtt.connected()){String id="equilink-esp32-"+String((uint32_t)ESP.getEfuseMac(),HEX);if(mqtt.connect(id.c_str(),MQTT_USER,MQTT_PASS)){mqtt.subscribe(T_R1R);mqtt.subscribe(T_R2R);mqtt.subscribe(T_P);}}}
void setup(){Serial.begin(115200);connectWiFi();net.setInsecure();mqtt.setServer(MQTT_HOST,MQTT_PORT);mqtt.setCallback(callback);}
void publishExample(){StaticJsonDocument<256>d;d["device_id"]="equilink-001";d["room"]="room1";d["timestamp"]=millis();JsonObject e=d.createNestedObject("electricity");e["voltage"]=220.4;e["current"]=1.25;e["power"]=275.5;e["energy_kwh"]=4.82;char buf[256];serializeJson(d,buf);mqtt.publish(T_R1,buf);}
void loop(){if(!mqtt.connected())reconnect();mqtt.loop();static unsigned long last=0;if(millis()-last>5000){last=millis();publishExample();}}
