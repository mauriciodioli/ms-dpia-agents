import time
import gspread

class SheetHandler:
    def __init__(self, sheet_manager, sheetId, sheet_name):
        self.sheet_manager = sheet_manager
        self.sheetId = sheetId
        self.sheet_name = sheet_name

    def leerSheet(self):
        try:
            sheet = self.sheet_manager.abrir_sheet(self.sheetId, self.sheet_name)
            if not sheet:
                print("No se pudo abrir la hoja")
                return None

            # Rangos de columnas esperados en el orden correcto (A a AC = 29 columnas)
            ranges = [
                'A:A',  # Producto
                'B:B',  # Categoría
                'C:C',  # País
                'D:D',  # Fuente
                'E:E',  # Motivo de tendencia
                'F:F',  # Descripción
                'G:G',  # precio_amazon
                'H:H',  # precio_ebay
                'I:I',  # precio_aliexpress
                'J:J',  # precio_venta_sugerido
                'K:K',  # margen_estimado               
                'L:L',  # fecha
                'M:M',  # motivo_tendencia_extendido
                'N:N',  # búsqueda_amazon
                'O:O',  # búsqueda_ebay
                'P:P',  # búsqueda_aliexpress
                'Q:Q',  # ambito
                'R:R',  # codigoPostal
                'S:S',  # usuario
                'T:T',  # estado
                'U:U',  # botonCompra
                'V:V',  # idioma
                'W:W',   # pagoOnline
                'X:X',  # validado
                'Y:Y',  # afiliado_link
            ]

            for _ in range(3):  # Hasta 3 intentos
                try:
                    data = sheet.batch_get(ranges)
                    if not data:
                        continue

                    columnas = []
                    for col in data:
                        if len(col) > 1:
                            columnas.append([str(item).strip("['").strip("']") for item in col[1:]])
                        else:
                            columnas.append([])

                    (
                        producto, categoria, pais, fuente, motivo_tendencia, descripcion,
                        precio_amazon, precio_ebay, precio_aliexpress,
                        precio_venta_sugerido, margen_estimado,
                        imagen, imagen2, imagen3, imagen4, imagen5, imagen6,
                        fecha, motivo_tendencia_extendido, busqueda_amazon, busqueda_ebay,
                        busqueda_aliexpress, ambito, codigo_postal, usuario,
                        estado, boton_compra, idioma, pago_online
                    ) = columnas

                    productos_data = zip(
                        producto, categoria, pais, fuente, motivo_tendencia, descripcion,
                        precio_amazon, precio_ebay, precio_aliexpress,
                        precio_venta_sugerido, margen_estimado,
                        imagen, imagen2, imagen3, imagen4, imagen5, imagen6,
                        fecha, motivo_tendencia_extendido, busqueda_amazon, busqueda_ebay,
                        busqueda_aliexpress, ambito, codigo_postal, usuario,
                        estado, boton_compra, idioma, pago_online
                    )
                    return productos_data

                except gspread.exceptions.APIError as e:
                    print(f"Error al leer la hoja: {e}")
                    if e.response.status_code == 500:
                        time.sleep(2)
                    else:
                        break
            return None

        except Exception as e:
            print(f"Error en el proceso de lectura: {e}")
            return None
