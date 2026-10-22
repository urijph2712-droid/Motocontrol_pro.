import sqlite3
from datetime import datetime
import pandas as pd
import streamlit as st

st.set_page_config(page_title="MotoControl Pro", page_icon="🏍️", layout="wide")

DB_PATH = "moto_control_pro.db"

# ============================================================
# BASE DE DATOS
# ============================================================
def get_connection():
    return sqlite3.connect(DB_PATH, check_same_thread=False)

def init_db():
    conn = get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            rol TEXT NOT NULL DEFAULT 'vendedor'
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS productos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            codigo TEXT UNIQUE NOT NULL,
            nombre TEXT NOT NULL,
            categoria TEXT DEFAULT 'General',
            precio REAL NOT NULL,
            stock INTEGER NOT NULL DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ventas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            producto_id INTEGER NOT NULL,
            codigo TEXT NOT NULL,
            nombre TEXT NOT NULL,
            categoria TEXT NOT NULL,
            cantidad INTEGER NOT NULL,
            precio_unitario REAL NOT NULL,
            total REAL NOT NULL,
            tipo_pago TEXT NOT NULL DEFAULT 'contado',
            monto_pagado REAL NOT NULL DEFAULT 0,
            monto_pendiente REAL NOT NULL DEFAULT 0,
            estado TEXT NOT NULL DEFAULT 'pagado',
            fecha TEXT NOT NULL,
            vendedor TEXT NOT NULL,
            FOREIGN KEY (producto_id) REFERENCES productos(id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS movimientos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            producto_id INTEGER NOT NULL,
            tipo TEXT NOT NULL,
            descripcion TEXT NOT NULL,
            cantidad INTEGER NOT NULL,
            fecha TEXT NOT NULL,
            vendedor TEXT NOT NULL,
            FOREIGN KEY (producto_id) REFERENCES productos(id)
        )
    """)
    conn.commit()
    conn.close()

def migrar_ventas():
    conn = get_connection()
    columnas = [row[1] for row in conn.execute("PRAGMA table_info(ventas)").fetchall()]

    if "tipo_pago" not in columnas:
        conn.execute("ALTER TABLE ventas ADD COLUMN tipo_pago TEXT NOT NULL DEFAULT 'contado'")
    if "monto_pagado" not in columnas:
        conn.execute("ALTER TABLE ventas ADD COLUMN monto_pagado REAL NOT NULL DEFAULT 0")
    if "monto_pendiente" not in columnas:
        conn.execute("ALTER TABLE ventas ADD COLUMN monto_pendiente REAL NOT NULL DEFAULT 0")
    if "estado" not in columnas:
        conn.execute("ALTER TABLE ventas ADD COLUMN estado TEXT NOT NULL DEFAULT 'pagado'")

    # completar valores antiguos
    conn.execute("""
        UPDATE ventas
        SET tipo_pago = 'contado',
            monto_pagado = total,
            monto_pendiente = 0,
            estado = 'pagado'
        WHERE tipo_pago IS NULL
    """)

    conn.commit()
    conn.close()

def crear_usuario_default():
    conn = get_connection()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO usuarios (usuario, password, rol) VALUES (?, ?, ?)",
            ("admin", "1234", "admin")
        )
        conn.execute(
            "INSERT OR IGNORE INTO usuarios (usuario, password, rol) VALUES (?, ?, ?)",
            ("vendedor", "1234", "vendedor")
        )
        conn.commit()
    finally:
        conn.close()

# ============================================================
# LOGIN
# ============================================================
def login(usuario, password):
    conn = get_connection()
    row = conn.execute(
        "SELECT usuario, rol FROM usuarios WHERE usuario = ? AND password = ?",
        (usuario, password)
    ).fetchone()
    conn.close()
    return row

# ============================================================
# PRODUCTOS
# ============================================================
def get_productos(filtro=""):
    conn = get_connection()
    if filtro:
        productos = conn.execute(
            """
            SELECT * FROM productos
            WHERE nombre LIKE ? OR codigo LIKE ? OR categoria LIKE ?
            ORDER BY nombre
            """,
            (f"%{filtro}%", f"%{filtro}%", f"%{filtro}%")
        ).fetchall()
    else:
        productos = conn.execute(
            "SELECT * FROM productos ORDER BY nombre"
        ).fetchall()
    conn.close()
    return productos

def agregar_producto(codigo, nombre, categoria, precio, stock):
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO productos (codigo, nombre, categoria, precio, stock)
            VALUES (?, ?, ?, ?, ?)
            """,
            (codigo.strip(), nombre.strip(), categoria.strip() or "General", precio, stock)
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def editar_producto(producto_id, codigo, nombre, categoria, precio, stock):
    conn = get_connection()
    try:
        conn.execute(
            """
            UPDATE productos
            SET codigo = ?, nombre = ?, categoria = ?, precio = ?, stock = ?
            WHERE id = ?
            """,
            (codigo.strip(), nombre.strip(), categoria.strip() or "General", precio, stock, producto_id)
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def eliminar_producto(producto_id):
    conn = get_connection()
    try:
        conn.execute("DELETE FROM productos WHERE id = ?", (producto_id,))
        conn.commit()
        return True
    finally:
        conn.close()

# ============================================================
# VENTAS / CRÉDITOS / MOVIMIENTOS
# ============================================================
def registrar_venta(producto_id, cantidad, vendedor, tipo_pago="contado", monto_pagado=0.0):
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT codigo, nombre, categoria, precio, stock FROM productos WHERE id = ?",
            (producto_id,)
        ).fetchone()

        if not row:
            st.warning("Producto no encontrado.")
            return False

        codigo, nombre, categoria, precio, stock_actual = row

        if cantidad <= 0:
            st.warning("La cantidad debe ser mayor a cero.")
            return False

        if cantidad > stock_actual:
            st.warning(f"Stock insuficiente. Disponible: {stock_actual}")
            return False

        total = precio * cantidad
        fecha = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if tipo_pago == "contado":
            monto_pagado = float(total)
            monto_pendiente = 0.0
            estado = "pagado"
        elif tipo_pago == "credito":
            monto_pagado = float(monto_pagado)
            if monto_pagado < 0:
                st.warning("El abono inicial no puede ser negativo.")
                return False
            if monto_pagado > total:
                st.warning("El abono inicial no puede ser mayor al total.")
                return False
            monto_pendiente = total - monto_pagado
            estado = "pendiente" if monto_pendiente > 0 else "pagado"
        else:
            st.warning("Tipo de pago no válido.")
            return False

        conn.execute(
            "UPDATE productos SET stock = stock - ? WHERE id = ?",
            (cantidad, producto_id)
        )

        conn.execute(
            """
            INSERT INTO ventas (
                producto_id, codigo, nombre, categoria, cantidad,
                precio_unitario, total, tipo_pago, monto_pagado, monto_pendiente,
                estado, fecha, vendedor
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                producto_id, codigo, nombre, categoria, cantidad,
                precio, total, tipo_pago, monto_pagado, monto_pendiente,
                estado, fecha, vendedor
            )
        )

        conn.execute(
            """
            INSERT INTO movimientos (
                producto_id, tipo, descripcion, cantidad, fecha, vendedor
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                producto_id,
                "venta",
                f"Venta de {cantidad} unidades ({tipo_pago})",
                -cantidad,
                fecha,
                vendedor
            )
        )

        conn.commit()

        if tipo_pago == "contado":
            st.success(f"Venta registrada: {cantidad} unidad(es) de {nombre}. Entrada neta: ${total:,.2f}")
        else:
            st.success(
                f"Venta a crédito registrada: {cantidad} unidad(es) de {nombre}. "
                f"Entrada neta: ${monto_pagado:,.2f} | Pendiente: ${monto_pendiente:,.2f}"
            )
        return True

    except Exception as e:
        st.error(f"Error al procesar la venta: {e}")
        return False
    finally:
        conn.close()

def registrar_ajuste(producto_id, cantidad, descripcion, vendedor):
    conn = get_connection()
    try:
        row = conn.execute("SELECT stock FROM productos WHERE id = ?", (producto_id,)).fetchone()
        if not row:
            st.warning("Producto no encontrado.")
            return False

        stock_actual = row[0]
        nuevo_stock = stock_actual + cantidad

        if nuevo_stock < 0:
            st.warning("No se puede dejar el stock en negativo.")
            return False

        conn.execute("UPDATE productos SET stock = ? WHERE id = ?", (nuevo_stock, producto_id))
        conn.execute(
            """
            INSERT INTO movimientos (producto_id, tipo, descripcion, cantidad, fecha, vendedor)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                producto_id,
                "ajuste",
                descripcion,
                cantidad,
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                vendedor
            )
        )
        conn.commit()
        return True
    finally:
        conn.close()

def cobrar_credito(venta_id, monto_recibido, vendedor):
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT total, monto_pagado, monto_pendiente, estado FROM ventas WHERE id = ?",
            (venta_id,)
        ).fetchone()

        if not row:
            st.warning("Venta no encontrada.")
            return False

        total, monto_pagado, monto_pendiente, estado = row

        if monto_recibido <= 0:
            st.warning("El cobro debe ser mayor a cero.")
            return False

        if estado == "pagado":
            st.info("Esta venta ya está pagada.")
            return False

        nuevo_pagado = monto_pagado + monto_recibido
        nuevo_pendiente = total - nuevo_pagado

        if nuevo_pagado > total:
            st.warning("El cobro excede el total de la venta.")
            return False

        if nuevo_pendiente <= 0:
            nuevo_estado = "pagado"
            nuevo_pendiente = 0.0
        else:
            nuevo_estado = "pendiente"

        conn.execute(
            """
            UPDATE ventas
            SET monto_pagado = ?, monto_pendiente = ?, estado = ?
            WHERE id = ?
            """,
            (nuevo_pagado, nuevo_pendiente, nuevo_estado, venta_id)
        )

        conn.execute(
            """
            INSERT INTO movimientos (producto_id, tipo, descripcion, cantidad, fecha, vendedor)
            VALUES (
                (SELECT producto_id FROM ventas WHERE id = ?),
                'cobro',
                'Cobro por crédito',
                0,
                ?,
                ?
            )
            """,
            (venta_id, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), vendedor)
        )

        conn.commit()
        st.success(f"Cobro registrado: ${monto_recibido:,.2f}")
        return True
    finally:
        conn.close()

# ============================================================
# REPORTES
# ============================================================
def obtener_ventas():
    conn = get_connection()
    ventas = conn.execute(
        """
        SELECT id, producto_id, codigo, nombre, categoria, cantidad,
               precio_unitario, total, tipo_pago, monto_pagado,
               monto_pendiente, estado, fecha, vendedor
        FROM ventas
        ORDER BY id DESC
        """
    ).fetchall()
    conn.close()
    return ventas

def obtener_creditos():
    conn = get_connection()
    creditos = conn.execute(
        """
        SELECT id, codigo, nombre, total, monto_pagado, monto_pendiente, estado, fecha, vendedor
        FROM ventas
        WHERE estado != 'pagado'
        ORDER BY id DESC
        """
    ).fetchall()
    conn.close()
    return creditos

def obtener_movimientos():
    conn = get_connection()
    mov = conn.execute(
        """
        SELECT id, producto_id, tipo, descripcion, cantidad, fecha, vendedor
        FROM movimientos
        ORDER BY id DESC
        """
    ).fetchall()
    conn.close()
    return mov

def resumen_ventas():
    conn = get_connection()
    row = conn.execute("""
        SELECT
            COALESCE(SUM(monto_pagado), 0) AS entrada_neta,
            COALESCE(SUM(monto_pendiente), 0) AS pendiente,
            COALESCE(SUM(total), 0) AS total_ventas
        FROM ventas
    """).fetchone()
    conn.close()
    return row

def dashboard_kpis():
    conn = get_connection()
    total_prod = conn.execute("SELECT COUNT(*) FROM productos").fetchone()[0]
    total_stock = conn.execute("SELECT COALESCE(SUM(stock), 0) FROM productos").fetchone()[0]
    total_ventas = conn.execute("SELECT COALESCE(SUM(total), 0) FROM ventas").fetchone()[0]
    conn.close()
    return total_prod, total_stock, total_ventas

# ============================================================
# APP
# ============================================================
init_db()
migrar_ventas()
crear_usuario_default()

if "usuario" not in st.session_state:
    st.session_state.usuario = None

if st.session_state.usuario is None:
    st.title("🔐 Acceso a MotoControl Pro")
    with st.form("login_form"):
        usuario = st.text_input("Usuario")
        password = st.text_input("Contraseña", type="password")
        submit = st.form_submit_button("Ingresar")

    if submit:
        data = login(usuario, password)
        if data:
            st.session_state.usuario = data[0]
            st.session_state.rol = data[1]
            st.rerun()
        else:
            st.error("Usuario o contraseña incorrectos.")
else:
    st.sidebar.write(f"👤 Usuario: {st.session_state.usuario}")
    st.sidebar.write(f"🛡️ Rol: {st.session_state.rol}")

    if st.sidebar.button("Cerrar sesión"):
        st.session_state.usuario = None
        st.session_state.rol = None
        st.rerun()

    st.title("🏍️ MotoControl Pro")

    total_prod, total_stock, total_ventas = dashboard_kpis()
    entrada_neta, pendiente, total_ventas_resumen = resumen_ventas()

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Productos", total_prod)
    col2.metric("Stock total", total_stock)
    col3.metric("Entrada neta", f"${entrada_neta:,.2f}")
    col4.metric("Pendiente por cobrar", f"${pendiente:,.2f}")

    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "🛒 Inventario",
        "➕ Nuevo producto",
        "📊 Ventas",
        "💳 Créditos",
        "⚙️ Ajustes"
    ])

    with tab1:
        filtro = st.text_input("Buscar repuesto", placeholder="Código, nombre o categoría")
        productos = get_productos(filtro)

        if not productos:
            st.info("No hay resultados.")
        else:
            for p in productos:
                p_id, codigo, nombre, categoria, precio, stock = p

                with st.container(border=True):
                    st.markdown(f"### {nombre}")
                    st.caption(f"SKU: `{codigo}` | Categoría: **{categoria}**")

                    colA, colB = st.columns(2)
                    colA.write(f"💵 **${precio:,.2f}**")
                    colB.write(f"📦 Stock: **{stock}**")

                    with st.form(f"venta_{p_id}"):
                        cantidad = st.number_input(
                            "Cantidad a vender",
                            min_value=1,
                            max_value=stock if stock > 0 else 1,
                            value=1,
                            key=f"cant_{p_id}"
                        )

                        tipo_pago = st.radio(
                            "Tipo de pago",
                            ["contado", "credito"],
                            horizontal=True,
                            key=f"tipo_{p_id}"
                        )

                        total_venta = precio * cantidad
                        if tipo_pago == "credito":
                            abono = st.number_input(
                                "Abono inicial",
                                min_value=0.0,
                                max_value=float(total_venta),
                                step=0.01,
                                value=0.0,
                                key=f"abono_{p_id}"
                            )
                        else:
                            abono = float(total_venta)

                        if st.form_submit_button("💸 Facturar"):
                            registrar_venta(p_id, cantidad, st.session_state.usuario, tipo_pago, abono)
                            st.rerun()

    with tab2:
        with st.form("form_add_product", clear_on_submit=True):
            codigo = st.text_input("Código / SKU")
            nombre = st.text_input("Nombre")
            categoria = st.text_input("Categoría")
            precio = st.number_input("Precio", min_value=0.0, step=0.01)
            stock = st.number_input("Stock inicial", min_value=0, step=1)
            if st.form_submit_button("Guardar"):
                if codigo and nombre:
                    if agregar_producto(codigo, nombre, categoria, precio, stock):
                        st.success("Producto guardado.")
                    else:
                        st.error("El código ya existe.")
                else:
                    st.warning("Completa los campos obligatorios.")

    with tab3:
        ventas = obtener_ventas()
        if not ventas:
            st.info("No hay ventas aún.")
        else:
            df = pd.DataFrame(
                ventas,
                columns=[
                    "id", "producto_id", "codigo", "nombre", "categoria", "cantidad",
                    "precio_unitario", "total", "tipo_pago", "monto_pagado",
                    "monto_pendiente", "estado", "fecha", "vendedor"
                ]
            )
            st.dataframe(df, use_container_width=True)
            st.download_button(
                "📥 Exportar CSV",
                data=df.to_csv(index=False).encode("utf-8"),
                file_name="ventas.csv",
                mime="text/csv"
            )

    with tab4:
        st.subheader("Control de créditos")

        creditos = obtener_creditos()
        if not creditos:
            st.info("No hay ventas pendientes.")
        else:
            for c in creditos:
                venta_id, codigo, nombre, total, monto_pagado, monto_pendiente, estado, fecha, vendedor = c
                st.markdown(f"### {nombre} | `{codigo}`")
                st.write(f"Total: ${total:,.2f} | Pagado: ${monto_pagado:,.2f} | Pendiente: ${monto_pendiente:,.2f}")
                st.write(f"Estado: **{estado}** | Fecha: {fecha} | Vendedor: {vendedor}")

                with st.form(f"cobro_{venta_id}"):
                    monto_recibido = st.number_input(
                        "Monto a cobrar",
                        min_value=0.0,
                        max_value=float(monto_pendiente) if monto_pendiente > 0 else 0.0,
                        step=0.01,
                        value=0.0,
                        key=f"monto_cobro_{venta_id}"
                    )
                    if st.form_submit_button("💵 Registrar cobro"):
                        cobrar_credito(venta_id, monto_recibido, st.session_state.usuario)
                        st.rerun()

    with tab5:
        st.subheader("Ajuste de stock")

        productos = get_productos()
        if productos:
            opcion = st.selectbox("Producto", [p[1] + " - " + p[2] for p in productos], index=0)
            prod_id = next(p[0] for p in productos if (p[1] + " - " + p[2]) == opcion)

            cantidad = st.number_input("Cantidad del ajuste", min_value=-1000, max_value=1000, step=1, value=0)
            descripcion = st.text_input("Descripción del ajuste", placeholder="Ej: devolución, inventario, pérdida")

            if st.button("Aplicar ajuste"):
                if registrar_ajuste(prod_id, int(cantidad), descripcion, st.session_state.usuario):
                    st.success("Ajuste realizado.")
                    st.rerun()
