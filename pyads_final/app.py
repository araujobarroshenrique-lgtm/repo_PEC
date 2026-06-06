def app(data_in, data_out):
    if data_in["tipo"] == "leblanc":
        data_out["tipocmd"] = "viktor"
    if data_in["dut_palavra"] == "renekton":
        data_out["dutcmd_palavracmd"] = "ngaballs"
    data_out["movex"] = data_in["posx"] + 1
    if data_out["movex"] >= 40:
        data_out["speedcmd"] = data_in["speed"] * 3 + data_in["state"]
    data_out["tempocmd"] = data_in["tempo"]+4
    return data_out