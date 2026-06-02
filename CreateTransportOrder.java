import java.rmi.RMISecurityManager;
import java.rmi.registry.LocateRegistry;
import java.rmi.registry.Registry;
import java.util.*;
import javax.naming.InitialContext;
import javax.naming.Context;

import org.opentcs.access.Kernel;
import org.opentcs.data.model.*;
import org.opentcs.data.order.*;

/**
 * 通过 Java RMI 直接调用 openTCS Kernel API 创建运输单
 */
public class CreateTransportOrder {

    public static void main(String[] args) throws Exception {
        String vehicleName = args.length > 0 ? args[0] : "AGV-001";
        String startPoint = args.length > 1 ? args[1] : "0";
        String endPoint = args.length > 2 ? args[2] : "3";

        System.out.println("=== openTCS Transport Order Creator ===");
        System.out.println("Vehicle: " + vehicleName);
        System.out.println("Route: " + startPoint + " -> " + endPoint);

        // 连接到 openTCS Kernel via RMI
        Registry registry = LocateRegistry.getRegistry("localhost", 1099);
        Kernel kernel = (Kernel) registry.lookup("kernel");

        if (kernel == null) {
            System.err.println("ERROR: Cannot connect to openTCS kernel!");
            System.exit(1);
        }
        System.out.println("[OK] Connected to openTCS kernel");

        // 创建运输单
        TransportOrder order = new TransportOrder(
            "auto-" + System.currentTimeMillis(),
            Arrays.asList(
                new DriveOrder(
                    new Point(startPoint),
                    new LoadOperation()
                ),
                new DriveOrder(
                    new Point(endPoint),
                    new UnloadOperation()
                )
            )
        );
        order.setIntendedVehicle(new Vehicle(vehicleName));

        System.out.println("[INFO] Creating transport order...");
        kernel.getTransportModelService().createTransportOrder(order);
        System.out.println("[OK] Transport order created: " + order.getName());

        // 触发调度
        kernel.getDispatcherService().dispatch();
        System.out.println("[OK] Dispatcher triggered");

        // 等待完成
        System.out.println("[INFO] Waiting for completion...");
        Thread.sleep(30000);
        System.out.println("[OK] Done");
    }
}
