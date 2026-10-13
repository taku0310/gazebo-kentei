(*
  仮想検定くん サンプルプログラム (IEC 61131-3 ST)

  動作仕様
    - PB1 運転 / PB2 停止 (自己保持)。運転中 L1 点灯、停止中 L2 点灯
    - SS1 OFF = 手動: PB3 を押している間 SOL1 (シリンダ前進)
    - SS1 ON  = 自動: 運転中にシリンダを 前進 -> LS2 で 1 秒停止 -> 後退 -> LS1 を 3 回繰り返す
                       3 回終わったら運転停止、L5 点灯、ブザー 1 秒
                       自動運転中は L4 が 0.5 秒周期で点滅
    - L3: シリンダ前進指令中
    - 異常: 前進指令から 3 秒以内に LS2 が ON しない -> L6 点滅 + ブザー、PB4 でリセット
    - 非常停止 EMG (b接点): 押されると全停止、L6 点滅 + ブザー

  I/O は仮想検定くん (Modbus スレーブ) を通して %IX100.0 / %QX100.0 以降に割り当てられる。
  変数宣言は `ros2 run kentei_sim kentei_openplc vars --config <yaml>` で生成できる。
*)
PROGRAM kentei_main
  VAR
    PB1 AT %IX100.0 : BOOL; (* X0 運転 *)
    PB2 AT %IX100.1 : BOOL; (* X1 停止 *)
    PB3 AT %IX100.2 : BOOL; (* X2 手動前進 *)
    PB4 AT %IX100.3 : BOOL; (* X3 異常リセット *)
    SS1 AT %IX100.4 : BOOL; (* X4 手動/自動 *)
    SS2 AT %IX100.5 : BOOL; (* X5 未使用 *)
    EMG AT %IX100.6 : BOOL; (* X6 非常停止 b接点 (正常時 TRUE) *)
    LS1 AT %IX100.7 : BOOL; (* X7 後退端 *)
    LS2 AT %IX101.0 : BOOL; (* X10 前進端 *)

    L1   AT %QX100.0 : BOOL; (* Y0 運転 *)
    L2   AT %QX100.1 : BOOL; (* Y1 停止 *)
    L3   AT %QX100.2 : BOOL; (* Y2 前進指令中 *)
    L4   AT %QX100.3 : BOOL; (* Y3 自動運転中 (点滅) *)
    L5   AT %QX100.4 : BOOL; (* Y4 完了 *)
    L6   AT %QX100.5 : BOOL; (* Y5 異常 (点滅) *)
    BZ   AT %QX100.6 : BOOL; (* Y6 ブザー *)
    SOL1 AT %QX100.7 : BOOL; (* Y7 シリンダ前進 *)
  END_VAR
  VAR
    run_flag   : BOOL;
    alarm      : BOOL;
    done       : BOOL;
    phase      : INT := 0;   (* 0:待機 1:前進 2:前進端待ち 3:後退 *)
    cycles     : INT := 0;
    pb1_edge   : R_TRIG;
    dwell      : TON;        (* 前進端での停止時間 *)
    stroke_chk : TON;        (* 前進タイムアウト監視 *)
    done_bz    : TP;         (* 完了ブザー *)
    blink_on   : TON;
    blink_off  : TON;
    blink      : BOOL;
  END_VAR

  (* 0.5 秒周期のフリッカ *)
  blink_on(IN := NOT blink_off.Q, PT := T#250ms);
  blink_off(IN := blink_on.Q, PT := T#250ms);
  blink := blink_on.Q;

  (* 運転の自己保持。異常中・非常停止中は運転できない *)
  pb1_edge(CLK := PB1);
  IF pb1_edge.Q AND NOT alarm AND EMG THEN
    run_flag := TRUE;
    done := FALSE;
    cycles := 0;
  END_IF;
  IF PB2 OR NOT EMG OR alarm THEN
    run_flag := FALSE;
  END_IF;

  (* 自動サイクル *)
  IF NOT (run_flag AND SS1) THEN
    phase := 0;
  ELSE
    CASE phase OF
      0: IF LS1 THEN phase := 1; END_IF;
      1: IF LS2 THEN phase := 2; END_IF;
      2: IF dwell.Q THEN phase := 3; END_IF;
      3: IF LS1 THEN
           cycles := cycles + 1;
           IF cycles >= 3 THEN
             run_flag := FALSE;
             done := TRUE;
             phase := 0;
           ELSE
             phase := 1;
           END_IF;
         END_IF;
    END_CASE;
  END_IF;
  dwell(IN := phase = 2, PT := T#1s);

  (* シリンダ出力: 自動の前進ステップ / 手動の PB3 *)
  SOL1 := EMG AND NOT alarm AND ((phase = 1) OR (phase = 2) OR (NOT SS1 AND PB3));

  (* 前進指令から 3 秒以内に前進端に着かなければ異常 *)
  stroke_chk(IN := SOL1 AND NOT LS2, PT := T#3s);
  IF stroke_chk.Q THEN
    alarm := TRUE;
  END_IF;
  IF PB4 AND EMG THEN
    alarm := FALSE;
  END_IF;

  done_bz(IN := done, PT := T#1s);

  L1 := run_flag;
  L2 := NOT run_flag;
  L3 := SOL1;
  L4 := run_flag AND SS1 AND blink;
  L5 := done;
  L6 := (alarm OR NOT EMG) AND blink;
  BZ := alarm OR NOT EMG OR done_bz.Q;
END_PROGRAM


CONFIGURATION Config0
  RESOURCE Res0 ON PLC
    TASK task0(INTERVAL := T#20ms, PRIORITY := 0);
    PROGRAM instance0 WITH task0 : kentei_main;
  END_RESOURCE
END_CONFIGURATION
