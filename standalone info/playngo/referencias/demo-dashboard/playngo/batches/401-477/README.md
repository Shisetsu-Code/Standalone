# Play’n GO · lote 401–477

77 fichas del catálogo original. Una entrada normal por demo y cada GoUltra publicado y habilitado que se identifique en el código específico del juego. Solo práctica oficial con saldo ficticio DEMO.

Las muestras especiales incluyen cuatro blackjack (una posición, Stand, sin seguro), Casino Hold’em (ante mínimo, sin AA, Fold), Mini Baccarat (jugador), dos ruedas (primera posición), tres póker (una mano, una moneda, reemplazo de las cinco cartas, sin gamble) y Keno (números 1 y 2). El póker usa la denominación mínima para una mano; no se afirma que sea el mínimo absoluto entre todas las cantidades de manos.

Se conservan tres solicitudes rechazadas de slots clásicos en rejected/ y tres repartos aceptados pero no terminados de diagnóstico en partial-deals/. Las manos completas posteriores se registran en sesiones demo nuevas. Los repartos parciales no cuentan como manos completadas ni como cierres conciliados.

Los paquetes nativos originales se conservan por paso. Los campos adicionales que el cliente oficial no lee se preservan sin asignarles significados supuestos. Keno omitió ceros finales en su confirmación, como permite getInt(index, default=0) del cliente público; se concilió su ronda original sin repetirla.

No se afirma cobertura de todas las apuestas de mesa, decisiones de blackjack, AA/Call/showdown de Hold’em, sorteos ganadores ni bonus naturales. La auditoría detalla únicamente los casos realmente observados.
