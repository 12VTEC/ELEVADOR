# ------------------------------------------------------------------------------
# ELEVADOR_12.0      -      MQTT - Adafruit IO
# ------------------------------------------------------------------------------
 
import machine, time, network, socket, os, gc, ubinascii
from umqtt.simple import MQTTClient

gc.collect()
print("\n--- INICIANDO SISTEMA 12VTEC - V12 MQTT ADAFRUIT ---")

def ler_dado(n, p):
    try:
        with open(n, 'r') as f: return f.read().strip()
    except: return str(p)

def salvar_dado(n, v):
    try:
        with open(n+'.tmp', 'w') as f: f.write(str(v))
        try: os.remove(n)
        except: pass
        os.rename(n+'.tmp', n)
    except: pass

_db_t = {}
_db_e = {}

def filtrar(pino, atual, id_p):
    ag = time.ticks_ms()
    v = pino.value()
    if v != _db_e.get(id_p, atual):
        _db_e[id_p] = v
        _db_t[id_p] = ag
    if time.ticks_diff(ag, _db_t.get(id_p, ag)) > 50:
        return v == 1
    return atual

PADRAO_CFG = ',,0.0.0.0,0.0.0.0,0.0.0.0,12vtec12,8.8.8.8,Elevador 12VTEC,aio_wDMX33pi8N4qlwL9rwE0rpMAGbhm,time.google.com'
try:
    partes = [x.strip() for x in ler_dado('config_rede.txt', PADRAO_CFG).split(',')]
    while len(partes) < 10: partes.append("")
    ssid_s, pass_s, ip_s, mask_s, gw_s, senha_tec, dns_s, nome_local, aio_key_s, ntp_s = partes[:10]
except:
    ssid_s, pass_s, ip_s, mask_s, gw_s, senha_tec, dns_s, nome_local, aio_key_s, ntp_s = "", "", "0.0.0.0", "0.0.0.0", "0.0.0.0", "12vtec12", "8.8.8.8", "Elevador 12VTEC", "aio_wDMX33pi8N4qlwL9rwE0rpMAGbhm", "time.google.com"

# Garantia contra valores em branco críticos
if not aio_key_s: aio_key_s = "aio_wDMX33pi8N4qlwL9rwE0rpMAGbhm"
if not ntp_s: ntp_s = "time.google.com"

try: timeout_ms = int(float(ler_dado('timeout.txt', 16100)))
except: timeout_ms = 16100

s1_c = s2_c = emerg_fisica = porta_aberta = 0
mot_s = machine.Pin(12, machine.Pin.OUT, value=0)
mot_d = machine.Pin(13, machine.Pin.OUT, value=0)
l1 = machine.Pin(14, machine.Pin.OUT, value=0)
l2 = machine.Pin(15, machine.Pin.OUT, value=0)

def parar_motores():
    mot_s.value(0)
    mot_d.value(0)

btn_pin = machine.Pin(34, machine.Pin.IN)
s1_pin = machine.Pin(35, machine.Pin.IN)
s2_pin = machine.Pin(36, machine.Pin.IN)
btn_emerg_pin = machine.Pin(39, machine.Pin.IN)
porta_pin = machine.Pin(33, machine.Pin.IN, machine.Pin.PULL_UP)

sta = network.WLAN(network.STA_IF)
if sta.isconnected():
    ip_r, mask_r, gw_r, dns_r = sta.ifconfig()
    ip_s = ip_r
    print("[Wi-Fi] Conexao herdada! IP:", ip_s)
    salvar_dado('dhcp.txt', f"{ip_r},{mask_r},{gw_r},{dns_r}")
else:
    ip_s = "12.12.12.12"
    print("[Wi-Fi] Sem rede externa. IP AP: 12.12.12.12")

modo_ap = (ip_s == "12.12.12.12")

lcd_ok = False
try:
    from i2c_lcd import I2cLcd
    i2c = machine.I2C(0, scl=machine.Pin(22), sda=machine.Pin(21), freq=400000)
    lcd = I2cLcd(i2c, 0x27, 4, 20)
    lcd_ok = True
except: pass

srv = None
dns_sock = None
if modo_ap:
    try:
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(('', 80))
        srv.listen(1)
        srv.setblocking(False)

        dns_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        dns_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        dns_sock.bind(('', 53))
        dns_sock.setblocking(False)
        print("[Web] Sockets AP abertos!")
    except Exception as e:
        print("[Web] Erro sockets:", e)

def processar_web():
    if dns_sock:
        try:
            req_d, addr_d = dns_sock.recvfrom(512)
            if len(req_d) >= 12:
                dns_sock.sendto(req_d[:2] + b'\x81\x80\x00\x01\x00\x01\x00\x00\x00\x00' + req_d[12:] + b'\xc0\x0c\x00\x01\x00\x01\x00\x00\x00\x3c\x00\x04\x0c\x0c\x0c\x0c', addr_d)
        except OSError: pass

    if not srv: return
    try:
        conn, addr = srv.accept()
        try:
            conn.settimeout(1.0)
            req = conn.recv(1024).decode('utf-8', 'ignore')
            if '/salvar?' in req:
                ini = req.find('/salvar?') + 8
                fim = req.find(' HTTP')
                if ini > 7 and fim > ini:
                    d = {"ssid":"", "senha":"", "ip":"", "mask":"", "gw":"", "dns":"", "local":"", "tec":"", "tipo":"DHCP", "tout":"16", "data":"", "hora":"", "aio_key":"", "ntp":""}
                    for par in req[ini:fim].split('&'):
                        if '=' in par:
                            k, v = par.split('=', 1)
                            if k in d: d[k] = v.replace('+', ' ').replace('%20', ' ').replace('%2F', '/').replace('%3A', ':')
                    eh_d = (d["tipo"] == "DHCP")
                    ip_e = "0.0.0.0" if eh_d else (d["ip"] or "0.0.0.0")
                    mk_e = "0.0.0.0" if eh_d else (d["mask"] or "255.255.255.0")
                    gw_e = "0.0.0.0" if eh_d else (d["gw"] or "0.0.0.0")
                    
                    # Salvando as 10 posições
                    salvar_dado('config_rede.txt', f"{d['ssid']},{d['senha']},{ip_e},{mk_e},{gw_e},{d['tec']},{d['dns']},{d['local']},{d['aio_key']},{d['ntp']}")
                    
                    try: salvar_dado('timeout.txt', int(float(d["tout"]) * 1000))
                    except: pass
                    try:
                        if d["data"] and d["hora"]:
                            dia, mes, ano = [int(x) for x in d["data"].split('/')]
                            hr, mn = [int(x) for x in d["hora"].split(':')]
                            machine.RTC().datetime((ano, mes, dia, 0, hr, mn, 0, 0))
                    except: pass
                    parar_motores()
                    conn.send(b"HTTP/1.1 200 OK\n\n<html><body style='background:#0a0a0a;color:cyan;text-align:center;padding:50px;'><h2>Salvo! Reiniciando...</h2></body></html>")
                    conn.close()
                    time.sleep(1)
                    machine.reset()

            elif '/restaurar' in req:
                parar_motores()
                ok = False
                try:
                    with open('restaura_main.py', 'r') as fr, open('main.py', 'w') as fw:
                        while True:
                            ped = fr.read(512)
                            if not ped: break
                            fw.write(ped)
                    ok = True
                except: pass
                msg, cor = ("Restaurado! Reiniciando...", "#27ae60") if ok else ("ERRO: Arquivo nao encontrado!", "#e74c3c")
                conn.send(f"HTTP/1.1 200 OK\n\n<html><body style='background:#0a0a0a;color:{cor};text-align:center;padding:50px;'><h2>{msg}</h2></body></html>".encode())
                conn.close()
                time.sleep(1)
                machine.reset()

            elif "GET " in req:
                p = [x.strip() for x in ler_dado('config_rede.txt', PADRAO_CFG).split(',')]
                while len(p) < 10: p.append("")
                m_dhcp = (p[2] in ["0.0.0.0", ""])
                if sta.isconnected(): ip_sh, mk_sh, gw_sh, dn_sh = sta.ifconfig()
                elif m_dhcp:
                    u_p = [x.strip() for x in ler_dado('dhcp.txt', ',,,').split(',')]
                    while len(u_p) < 4: u_p.append("")
                    ip_sh, mk_sh, gw_sh, dn_sh = u_p[:4]
                else: ip_sh, mk_sh, gw_sh, dn_sh = p[2], p[3], p[4], p[6]

                ip_sh = "" if ip_sh == "0.0.0.0" else ip_sh
                mk_sh = "" if mk_sh == "0.0.0.0" else mk_sh
                gw_sh = "" if gw_sh == "0.0.0.0" else gw_sh
                dn_sh = "" if dn_sh == "0.0.0.0" else dn_sh
                try: t_out = str(int(float(ler_dado('timeout.txt', 16100))) / 1000.0)
                except: t_out = "16.0"
                tb = time.localtime()

                conn.send(b"HTTP/1.1 200 OK\nContent-Type: text/html\n\n<!DOCTYPE html><html><head><meta name='viewport' content='width=device-width,initial-scale=1'><style>body{background:#0a0a0a;color:cyan;font-family:sans-serif;padding:15px;text-align:center}input,select{background:#111;color:cyan;border:1px solid cyan;padding:10px;width:95%;margin-bottom:12px;border-radius:5px;box-sizing:border-box}input[readonly]{background:#222;color:#777;border-color:#555}.btn{background:#27ae60;color:#000;font-weight:bold;border:none;margin-top:10px;padding:15px;width:95%;border-radius:8px}.btn2{background:#e74c3c;color:#fff;font-weight:bold;border:none;margin-top:20px;padding:15px;width:95%;border-radius:8px}.lbl{text-align:left;width:95%;display:block;margin:0 auto 5px;font-size:12px;color:#008b8b;font-weight:bold}</style><script>function mT(){var d=document.getElementById('t').value==='DHCP';['i','m','g','d'].forEach(function(id){document.getElementById(id).readOnly=d;});}window.onload=mT;</script></head><body><div style='border:2px solid cyan;border-radius:8px;padding:12px;background:#000;width:95%;box-sizing:border-box;display:inline-block'><h1 style='margin:0;color:cyan'>12VTEC</h1><span style='color:#008b8b;font-size:12px;font-weight:bold'>TECNOLOGIA</span></div><h4 style='color:#27ae60'>Elevador de Carga - V.12</h4><h3>REDE E CONECTIVIDADE</h3><form action='/salvar'>")
                # Novos campos inseridos no HTML dinâmico
                conn.send(f"<span class='lbl'>SSID Wi-Fi:</span><input type='text' name='ssid' value='{p[0]}'><span class='lbl'>Senha Wi-Fi:</span><input type='text' name='senha' value='{p[1]}'><span class='lbl'>Modo:</span><select name='tipo' id='t' onchange='mT()'><option value='DHCP' {'selected' if m_dhcp else ''}>DHCP (IP Dinamico)</option><option value='Fixo' {'' if m_dhcp else 'selected'}>Manual (IP Fixo)</option></select><span class='lbl'>IP:</span><input type='text' id='i' name='ip' value='{ip_sh}'><span class='lbl'>Mascara:</span><input type='text' id='m' name='mask' value='{mk_sh}'><span class='lbl'>Gateway:</span><input type='text' id='g' name='gw' value='{gw_sh}'><span class='lbl'>DNS:</span><input type='text' id='d' name='dns' value='{dn_sh}'><hr style='border:1px solid #333;margin:20px 0'><h3>CONFIGURACOES GERAIS</h3><span class='lbl'>Nome Local:</span><input type='text' name='local' value='{p[7]}'><span class='lbl'>Chave Adafruit (AIO):</span><input type='password' name='aio_key' value='{p[8]}'><span class='lbl'>Servidor NTP:</span><input type='text' name='ntp' value='{p[9]}'><span class='lbl'>Senha Tecnico:</span><input type='password' name='tec' value='{p[5]}'><span class='lbl'>Timeout(s):</span><input type='text' name='tout' value='{t_out}'><span class='lbl'>Data (D/M/A):</span><input type='text' name='data' value='{tb[2]:02d}/{tb[1]:02d}/{tb[0]:04d}'><span class='lbl'>Hora (H:M):</span><input type='text' name='hora' value='{tb[3]:02d}:{tb[4]:02d}'><input type='submit' class='btn' value='SALVAR E ENVIAR'></form><form action='/restaurar'><input type='submit' class='btn2' value='RESTAURAR FIRMWARE'></form></body></html>".encode())
        except: pass
        finally:
            try: conn.close()
            except: pass
    except OSError: pass

print("\n[Transicao] Iniciando Fase 2 (MQTT Adafruit + Hardware)...")
gc.collect()

ADAFRUIT_SERVER = "io.adafruit.com"
ADAFRUIT_USER = "12vtec"
ADAFRUIT_KEY = aio_key_s  # Agora puxa da variável lida no arquivo!
TOPICO_COMANDO = b"12vtec/feeds/comando"
TOPICO_RESET = b"12vtec/feeds/reset"
TOPICO_STATUS = b"12vtec/feeds/status"

try: CLIENT_ID = "12vtec_" + ubinascii.hexlify(sta.config('mac')).decode()
except: CLIENT_ID = "12vtec_elevador_prod"

mqtt_cliente = None
mqtt_conectado = False
botao_virtual_nuvem = False
fila_mensagens_nuvem = []
envio_log_ativo = False
faturas_log = []
indice_fatura = 0

DIC_LOGS = {
    "Em.Rearm": "EMERGÊNCIA REARME",
    "Em.Painl": "EMERGÊNCIA ACIONADA",
    "TmOut Sb": "FALHA SENSOR: TIMEOUT SUBIDA",
    "TmOut Ds": "FALHA SENSOR: TIMEOUT DESCIDA",
    "TmOut Ch": "FALHA SENSOR: TIMEOUT DESCIDA CALIBRANDO",
    "TmOut Tp": "FALHA SENSOR: TIMEOUT SUBIDA CALIBRANDO",
    "Bloq. Em": "BLOQUEIO DE EMERGÊNCIA",
    "Bloq. Pt": "BLOQUEIO DE PORTA",
    "Cancelad": "MOVIMENTO CANCELADO",
    "Alt. TmO": "TEMPO DE TIMEOUT ALTERADO",
    "Calib_TmO": "TIMEOUT ALTERADO POR CALIBRAÇÃO",
    "Rst.Diar": "RESET DIARIO PREVENTIVO"
}

def aviso_nuvem(msg, prefixo="[INFO] "):
    if mqtt_conectado:
        fila_mensagens_nuvem.append((prefixo + msg).encode())
        if len(fila_mensagens_nuvem) > 15: fila_mensagens_nuvem.pop(0)

def enviar_status_imediato(txt):
    global ultimo_status_mqtt_enviado, ultimo_envio_mqtt
    ultimo_status_mqtt_enviado = txt
    if sta.isconnected() and mqtt_conectado and mqtt_cliente:
        try:
            mqtt_cliente.publish(TOPICO_STATUS, ("[INFO] " + txt).encode())
            ultimo_envio_mqtt = time.ticks_ms()
            time.sleep_ms(50)
        except: pass

def registrar_log_real(motivo, extra=""):
    if motivo not in DIC_LOGS and not motivo.startswith("REDE"): return
    motivo_fmt = DIC_LOGS.get(motivo, motivo)
    if extra: motivo_fmt += f" - {extra}"
    try:
        tb = time.localtime()
        nova = "[{:02d}/{:02d}/{:02d} {:02d}:{:02d}] {}".format(tb[2], tb[1], tb[0]%100, tb[3], tb[4], motivo_fmt) if tb[0] > 2020 else f"[RTC Falhou] {motivo_fmt}"
        linhas = []
        try:
            with open('log.txt', 'r') as f:
                linhas = [l.strip() for l in f if l.strip()]
        except: pass
        linhas.insert(0, nova)
        with open('log.txt', 'w') as f:
            for l in linhas[:30]: f.write(l + '\n')
        if mqtt_conectado:
            fila_mensagens_nuvem.append(b"[INFO] " + motivo_fmt.encode())
    except: pass

def recebi_comando(topico, mensagem):
    global timeout_ms, botao_virtual_nuvem, envio_log_ativo, faturas_log, indice_fatura
    try:
        cmd = mensagem.decode().strip()
        cmd_up = cmd.upper()

        if cmd_up in ["ACIONAR", "1", "ON", "TRUE"]:
            botao_virtual_nuvem = True

        elif cmd_up == "RESET":
            parar_motores()
            if mqtt_cliente:
                try: mqtt_cliente.publish(TOPICO_STATUS, b"[ATENCAO] [SISTEMA] Reiniciando...")
                except: pass
            time.sleep(1)
            machine.reset()

        elif cmd_up == "PING":
            try:
                tb = time.localtime()
                t_out_seg = timeout_ms / 1000.0
                if mqtt_cliente: mqtt_cliente.publish(TOPICO_STATUS, f"[PONG] {tb[2]:02d}/{tb[1]:02d}/{tb[0]%100:02d} {tb[3]:02d}:{tb[4]:02d} {t_out_seg:.1f}".encode())
            except: pass

        elif cmd.startswith("HR:"):
            try:
                h, m = cmd[3:].split(":")
                tb = time.localtime()
                machine.RTC().datetime((tb[0], tb[1], tb[2], 0, int(h), int(m), 0, 0))
                if mqtt_cliente: mqtt_cliente.publish(TOPICO_STATUS, f"[INFO] Hora: {h}:{m}".encode())
            except: pass

        elif cmd.startswith("DT:"):
            try:
                d, m, a = cmd[3:].split("/")
                if len(a) == 2: a = "20" + a
                tb = time.localtime()
                machine.RTC().datetime((int(a), int(m), int(d), 0, tb[3], tb[4], 0, 0))
                if mqtt_cliente: mqtt_cliente.publish(TOPICO_STATUS, f"[INFO] Data: {d}/{m}/{a}".encode())
            except: pass

        elif cmd_up == "LISTAR_ARQUIVOS":
            try:
                arqs = [f for f in os.listdir() if not f.startswith('.')]
                if mqtt_cliente: mqtt_cliente.publish(TOPICO_STATUS, ("[ARQUIVOS]" + ",".join(arqs)).encode())
            except: pass

        elif cmd_up == "BAIXAR_LOG":
            try:
                linhas = []
                try:
                    with open('log.txt', 'r') as f:
                        linhas = [l.strip() for l in f if l.strip()][:30]
                except: pass
                if linhas:
                    l_env = list(reversed(linhas))
                    faturas_log = [f"[LOG_COMPLETO] {' || '.join(l_env[i:i+10])}" for i in (0, 10, 20) if l_env[i:i+10]]
                    indice_fatura = 0
                    envio_log_ativo = True
                else:
                    if mqtt_cliente: mqtt_cliente.publish(TOPICO_STATUS, b"[LOG_COMPLETO] Log vazio")
            except: pass

        elif cmd_up.startswith("APAGAR:"):
            try:
                arq = cmd.split(":", 1)[1].strip()
                if arq.lower() in ["main.py", "main.mpy", "boot.py", "i2c_lcd.py", "restaura_boot.py", "restaura_main.py"]:
                    if mqtt_cliente: mqtt_cliente.publish(TOPICO_STATUS, b"[ERRO] Proibido apagar arquivos de sistema!")
                else:
                    os.remove(arq)
                    if mqtt_cliente:
                        mqtt_cliente.publish(TOPICO_STATUS, f"[SUCESSO] Arquivo {arq} apagado!".encode())
                        time.sleep_ms(300)
                        arqs = [f for f in os.listdir() if not f.startswith('.')]
                        mqtt_cliente.publish(TOPICO_STATUS, ("[ARQUIVOS]" + ",".join(arqs)).encode())
            except:
                if mqtt_cliente: mqtt_cliente.publish(TOPICO_STATUS, b"[ERRO] Arquivo nao encontrado.")

        elif cmd_up in ["LER_REDE", "GET_REDE", "CONFIG_REDE", "REDE", "LER_CONFIG"]:
            try:
                p = [x.strip() for x in ler_dado('config_rede.txt', PADRAO_CFG).split(',')]
                while len(p) < 10: p.append("")
                modo_cfg = "DHCP" if p[2] in ["0.0.0.0", ""] else "Fixo"
                ip_r, mask_r, gw_r, dns_r = sta.ifconfig() if sta.isconnected() else (p[2], p[3], p[4], p[6])
                t_out = timeout_ms / 1000.0
                if mqtt_cliente:
                    # Agora envia os 12 parâmetros (incluindo chave e NTP lidos no config)
                    mqtt_cliente.publish(TOPICO_STATUS, f"[CFG]{p[0]},{p[1]},{ip_r},{mask_r},{gw_r},{p[5]},{dns_r},{p[7]},{modo_cfg},{t_out},{p[8]},{p[9]}".encode())
            except: pass

        elif cmd_up.startswith("SALVAR_REDE:") or cmd_up.startswith("GRAVAR_REDE:"):
            try:
                parar_motores()
                salvar_dado('config_rede.txt', cmd.split(":", 1)[1].strip())
                if mqtt_cliente: mqtt_cliente.publish(TOPICO_STATUS, b"[INFO] Configuracao Salva! Reiniciando...")
                time.sleep(1)
                machine.reset()
            except: pass

        elif cmd_up.startswith("OTA_DRIVE:"):
            try:
                p_ota = cmd.split("OTA_DRIVE:")[1].strip().split('|', 1)
                if len(p_ota) == 2:
                    parar_motores()
                    with open('preciso_atualizar.txt', 'w') as f: f.write(f"{p_ota[0].strip()}|{p_ota[1].strip()}")
                    if mqtt_cliente:
                        mqtt_cliente.publish(TOPICO_STATUS, f"[SUCESSO] Flag OTA criada para {p_ota[0].strip()}. Reiniciando...".encode())
                        time.sleep_ms(500)
                        mqtt_cliente.disconnect()
                    time.sleep(1.5)
                    machine.reset()
            except: pass

        else:
            try:
                val_num = float(cmd.replace(',', '.'))
                timeout_ms = int(val_num * 1000) if val_num <= 60 else int(val_num)
                salvar_dado('timeout.txt', timeout_ms)
                registrar_log_real("Alt. TmO", "{:.1f}s".format(timeout_ms / 1000.0).replace('.', ','))
            except: pass
    except: pass

def sincronizar_logs_offline():
    try:
        with open('log.txt', 'r') as f:
            ult = f.readline().strip()
        if ult and ult != ler_dado('ult_log_env.txt', ''):
            if mqtt_conectado: fila_mensagens_nuvem.append(ult.encode())
            salvar_dado('ult_log_env.txt', ult)
    except: pass

def conectar_mqtt():
    global mqtt_cliente, mqtt_conectado
    try:
        if sta.isconnected():
            if mqtt_cliente:
                try: mqtt_cliente.sock.close()
                except: pass
                mqtt_cliente = None
            gc.collect()
            c = MQTTClient(client_id=CLIENT_ID, server=ADAFRUIT_SERVER, port=1883, user=ADAFRUIT_USER, password=ADAFRUIT_KEY, keepalive=60)
            c.set_callback(recebi_comando)
            c.connect()
            c.subscribe(TOPICO_COMANDO)
            c.subscribe(TOPICO_RESET)
            mqtt_cliente = c
            mqtt_conectado = True
            print("[MQTT] Conectado ao Adafruit IO!")
            sincronizar_logs_offline()
    except Exception as e:
        print("[MQTT] Falha:", e)
        mqtt_conectado = False
        if mqtt_cliente:
            try: mqtt_cliente.sock.close()
            except: pass
            mqtt_cliente = None
        gc.collect()

conectar_mqtt()
print("[Fase 2] Controle de Hardware Mecanico Iniciado.")

try: wdt = machine.WDT(timeout=30000)
except: wdt = machine.WDT()

def alerta_falha():
    parar_motores()
    for _ in range(3):
        l1.value(1); l2.value(1); time.sleep_ms(150)
        l1.value(0); l2.value(0); time.sleep_ms(150)

lcd_minuto = -99
lcd_status = lcd_log = lcd_rede = ""
ultimo_status_mqtt_enviado = ""
ultimo_envio_mqtt = ultimo_tentativa_reconexao = ultimo_tentativa_wifi = time.ticks_ms()
ultimo_check_relogio = ultimo_gc = ultimo_ping_mqtt = time.ticks_ms()

estado_rede_anterior = None
ultima_direcao = int(ler_dado('direcao.txt', 2))
calib_step = calib_timer = passo_falta = tempo_passo_falta = 0
last_ms = last_stop = inicio_movimento = btn_press_time = led_state = estado = btn_f = 0

try:
    while True:
        wdt.feed()
        now = time.ticks_ms()

        if modo_ap:
            processar_web()

        if estado == 0 and envio_log_ativo and mqtt_conectado and mqtt_cliente:
            try:
                if indice_fatura < len(faturas_log):
                    mqtt_cliente.publish(TOPICO_STATUS, faturas_log[indice_fatura].encode())
                    indice_fatura += 1
                else:
                    envio_log_ativo = False
            except:
                envio_log_ativo = False

        wifi_conectado = (not modo_ap) and sta.isconnected()

        if wifi_conectado:
            if mqtt_conectado and mqtt_cliente:
                try:
                    mqtt_cliente.check_msg()
                    if time.ticks_diff(now, ultimo_ping_mqtt) > 45000:
                        mqtt_cliente.ping()
                        ultimo_ping_mqtt = now
                    if fila_mensagens_nuvem and time.ticks_diff(now, ultimo_envio_mqtt) > 2000:
                        msg = fila_mensagens_nuvem.pop(0)
                        try:
                            mqtt_cliente.sock.settimeout(0.02)
                            mqtt_cliente.publish(TOPICO_STATUS, msg)
                        except: pass
                        finally:
                            mqtt_cliente.sock.settimeout(None)
                        ultimo_envio_mqtt = now
                except OSError:
                    mqtt_conectado = False
                    if mqtt_cliente:
                        try: mqtt_cliente.sock.close()
                        except: pass
                        mqtt_cliente = None
                    gc.collect()
            else:
                if estado == 0 and not btn_f and time.ticks_diff(now, ultimo_tentativa_reconexao) > 180000:
                    ultimo_tentativa_reconexao = now
                    conectar_mqtt()
        else:
            mqtt_conectado = False
            if mqtt_cliente:
                try: mqtt_cliente.sock.close()
                except: pass
                mqtt_cliente = None
                gc.collect()

            if not modo_ap and ssid_s and estado == 0 and not btn_f:
                if time.ticks_diff(now, ultimo_tentativa_wifi) > 30000:
                    ultimo_tentativa_wifi = now
                    try:
                        sta.disconnect()
                        time.sleep_ms(100)
                        sta.connect(ssid_s, pass_s)
                    except: pass

        if estado == 0:
            est_atual = (wifi_conectado, mqtt_conectado)
            if est_atual != estado_rede_anterior:
                if estado_rede_anterior is not None:
                    registrar_log_real(f"REDE WIFI {'ON' if wifi_conectado else 'OFF'} - ADAFRUIT {'ON' if mqtt_conectado else 'OFF'}")
                estado_rede_anterior = est_atual

        if estado == 0 and time.ticks_diff(now, ultimo_check_relogio) > 1800000:
            ultimo_check_relogio = now
            tb_atual = time.localtime()
            
            if tb_atual[3] == 4 and tb_atual[4] < 30:
                try:
                    parar_motores()
                    registrar_log_real("Rst.Diar")
                    time.sleep_ms(1000)
                    machine.reset()
                except: pass

        if estado == 0 and time.ticks_diff(now, ultimo_gc) > 30000:
            gc.collect()
            ultimo_gc = now

        s1_c = filtrar(s1_pin, s1_c, 's1')
        s2_c = filtrar(s2_pin, s2_c, 's2')
        btn_f_prev, btn_f = btn_f, filtrar(btn_pin, btn_f, 'btn')

        emerg_fisica_prev, emerg_fisica = emerg_fisica, (btn_emerg_pin.value() == 0)
        porta_aberta_prev, porta_aberta = porta_aberta, (porta_pin.value() == 1)
        diff_stop = time.ticks_diff(now, last_stop)

        if estado == 5:
            if calib_step in (1, 3): t_ex_sec = time.ticks_diff(now, calib_timer) / 1000.0
            elif calib_step == 2: t_ex_sec = max(0, 2000 - time.ticks_diff(now, calib_timer)) / 1000.0
        else:
            t_ex_sec = (max(0, timeout_ms - time.ticks_diff(now, inicio_movimento)) / 1000.0) if estado in (1, 2) else (timeout_ms / 1000.0)

        if emerg_fisica and estado != 3:
            estado = 3; parar_motores(); calib_step = 0; last_stop = now
            registrar_log_real("Em.Painl")
        elif not emerg_fisica and porta_aberta and estado not in (3, 4, 6):
            estado = 4; parar_motores(); calib_step = 0; last_stop = now
        if emerg_fisica_prev and not emerg_fisica and estado == 3:
            estado = 4 if porta_aberta else 0; last_stop = now
            registrar_log_real("Em.Rearm")
        if porta_aberta_prev and not porta_aberta and estado == 4:
            estado = 0; last_stop = now

        trigger_normal = False
        if botao_virtual_nuvem:
            botao_virtual_nuvem = False
            trigger_normal = True

        if btn_f and not btn_f_prev:
            btn_press_time = now
        elif not btn_f and btn_f_prev:
            duracao = time.ticks_diff(now, btn_press_time)
            if duracao >= 10000:
                if estado == 0 and not emerg_fisica and not porta_aberta:
                    enviar_status_imediato("CALIBRANDO DESCENDO")
                    now = time.ticks_ms()
                    estado = 5; calib_step = 1; calib_timer = now
            elif duracao > 50:
                trigger_normal = True

        segurando_calib = (btn_f and estado == 0 and time.ticks_diff(now, btn_press_time) >= 10000 and not emerg_fisica and not porta_aberta)
        txt_calib = "CALIBRANDO SUBINDO" if calib_step == 3 else "CALIBRANDO DESCENDO"

        if estado == 0:
            st_txt = "CALIBRAGEM" if segurando_calib else ("EM BAIXO" if s1_c else ("EM CIMA" if s2_c else "PARADO"))
        elif estado == 6: st_txt = "FALTA SENSOR" if (now // 500) % 2 == 0 else ""
        elif estado == 3: st_txt = "EMERGENCIA" if (now // 500) % 2 == 0 else ""
        elif estado == 4: st_txt = "PORTA ABERTA"
        elif estado == 5: st_txt = txt_calib
        elif estado == 1: st_txt = "SUBINDO"
        elif estado == 2: st_txt = "DESCENDO"
        else: st_txt = ""

        if st_txt != ultimo_status_mqtt_enviado and st_txt != "":
            ultimo_status_mqtt_enviado = st_txt
            if estado not in (3, 6):
                aviso_nuvem(st_txt, "[INFO] ")

        if lcd_ok:
            try:
                tb = time.localtime()
                if tb[4] != lcd_minuto:
                    str_dh = "{:02d}/{:02d}/{:04d} {:02d}:{:02d}".format(tb[2], tb[1], tb[0], tb[3], tb[4]) if tb[0] > 2020 else "RTC FALHA BATERIA"
                    esp = 20 - len(str_dh)
                    lcd.move_to(0, 0); lcd.putstr(((" " * (esp // 2)) + str_dh + (" " * (esp - (esp // 2))))[:20])
                    lcd_minuto = tb[4]

                txt_l2 = f"IP:{ip_s} {'ON' if mqtt_conectado else 'OFF'}"
                if txt_l2 != lcd_rede:
                    lcd.move_to(0, 1); lcd.putstr((txt_l2 + "                    ")[:20])
                    lcd_rede = txt_l2

                if lcd_log != "LIMPO":
                    lcd.move_to(0, 2); lcd.putstr("                    ")
                    lcd_log = "LIMPO"

                if estado == 1: st_lcd = f"SUBINDO {t_ex_sec:.1f}s"
                elif estado == 2: st_lcd = f"DESCENDO {t_ex_sec:.1f}s"
                elif estado == 5 and calib_step == 3: st_lcd = f"CALIB SUBINDO {t_ex_sec:.1f}s"
                elif estado == 5: st_lcd = "CALIBRANDO DESCENDO"
                else: st_lcd = st_txt

                if st_lcd != lcd_status:
                    txt_l4 = st_lcd if estado == 5 else f"STATUS: {st_lcd}"
                    lcd.move_to(0, 3); lcd.putstr((txt_l4 + "                    ")[:20])
                    lcd_status = st_lcd
            except: pass

        if estado in (1, 2, 5) and trigger_normal:
            parar_motores(); estado = 0; last_stop = now; calib_step = 0; aviso_nuvem("MOVIMENTO CANCELADO")
        elif estado == 6 and trigger_normal:
            parar_motores(); estado = 0; last_stop = now
        elif estado == 0 and trigger_normal:
            if emerg_fisica: registrar_log_real("Bloq. Em")
            elif porta_aberta: registrar_log_real("Bloq. Pt")
            elif diff_stop > 2000:
                estado = 1 if s1_c else (2 if s2_c else (2 if ultima_direcao == 1 else 1))
                ultima_direcao = estado; salvar_dado('direcao.txt', ultima_direcao)
                enviar_status_imediato("SUBINDO" if estado == 1 else "DESCENDO")
                now = time.ticks_ms()
                inicio_movimento = last_stop = now
        elif estado == 3 and not emerg_fisica and trigger_normal:
            estado = 4 if porta_aberta else 0; last_stop = now

        if estado == 0:
            parar_motores(); l1.value(1 if s1_c else 0); l2.value(1 if s2_c else 0)
        elif estado == 1:
            mot_s.value(1); mot_d.value(0); l1.value(1 if s1_c else 0); l2.value(1 if s2_c else 0)
            if s2_c or (time.ticks_diff(now, inicio_movimento) > timeout_ms):
                mot_s.value(0); last_stop = now
                if time.ticks_diff(now, inicio_movimento) > timeout_ms:
                    estado = 6; passo_falta = 0; tempo_passo_falta = now; registrar_log_real("TmOut Sb")
                else: estado = 0
        elif estado == 2:
            mot_d.value(1); mot_s.value(0); l1.value(1 if s1_c else 0); l2.value(1 if s2_c else 0)
            if s1_c or (time.ticks_diff(now, inicio_movimento) > timeout_ms):
                mot_d.value(0); last_stop = now
                if time.ticks_diff(now, inicio_movimento) > timeout_ms:
                    estado = 6; passo_falta = 0; tempo_passo_falta = now; registrar_log_real("TmOut Ds")
                else: estado = 0
        elif estado in (3, 4):
            parar_motores()
            t_pisca = 300 if estado == 3 else 1000
            if time.ticks_diff(now, last_ms) > t_pisca:
                led_state = 1 - led_state; l1.value(led_state); l2.value(led_state); last_ms = now
        elif estado == 6:
            parar_motores()
            dt_falta = time.ticks_diff(now, tempo_passo_falta)
            if passo_falta < 6:
                if dt_falta > 150:
                    led_state = 1 - led_state; l1.value(led_state); l2.value(led_state)
                    passo_falta += 1; tempo_passo_falta = now
            else:
                l1.value(0); l2.value(0)
                if dt_falta > 1000: passo_falta = 0; tempo_passo_falta = now
        elif estado == 5:
            if time.ticks_diff(now, last_ms) > 150:
                led_state = 1 - led_state; l1.value(led_state); l2.value(led_state); last_ms = now

            if calib_step == 1:
                mot_d.value(1); mot_s.value(0)
                if (s1_pin.value() == 1) or time.ticks_diff(now, calib_timer) > 20000:
                    mot_d.value(0)
                    if time.ticks_diff(now, calib_timer) > 20000:
                        parar_motores(); estado = 0; alerta_falha(); registrar_log_real("TmOut Ch")
                    else: calib_step = 2; calib_timer = now

            elif calib_step == 2:
                parar_motores()
                if time.ticks_diff(now, calib_timer) > 2000:
                    enviar_status_imediato("CALIBRANDO SUBINDO")
                    now = time.ticks_ms()
                    mot_s.value(1); calib_step = 3; calib_timer = now

            elif calib_step == 3:
                mot_s.value(1); mot_d.value(0)
                if (s2_pin.value() == 1) or time.ticks_diff(now, calib_timer) > 20000:
                    mot_s.value(0)
                    if time.ticks_diff(now, calib_timer) > 20000:
                        parar_motores(); estado = 0; alerta_falha(); registrar_log_real("TmOut Tp")
                    else:
                        timeout_ms = time.ticks_diff(now, calib_timer) + 1000
                        salvar_dado('timeout.txt', timeout_ms)
                        estado = 0; calib_step = 0; last_stop = now
                        registrar_log_real("Calib_TmO", "{:.1f}s".format(timeout_ms / 1000.0).replace('.', ','))

        time.sleep_ms(20) 

except Exception as e:
    parar_motores()
    print("[Erro Critico]:", e)
    time.sleep(2)
    machine.reset()