import cv2
import time
import numpy as np
from ultralytics import YOLO
import serial
import data_parser
import mqtt_publisher

# Load YOLOv8 model
model = YOLO('new.pt', task='detect')
print(model.names)

# Initialize web camera
webcamera = cv2.VideoCapture(0)
webcamera.set(3,640)
webcamera.set(4,480)

# Parameters for distance estimation
KNOWN_WIDTH = 35
KNOWN_DIST = 90
FOCAL_LENGTH = (600, 630)
conv_factor = 0.1419
# KNOWN_HEIGHT = 3  # meters (example: height of a person)
# FOCAL_LENGTH = 2000 # example value in pixels (calibrate your camera to get this value)

# FPS PARAM
prev_frame_time = 0
new_frame_time = 0

# Serial Mode
serial_port = '/dev/serial/by-id/usb-FTDI_FT232R_USB_UART_A50285BI-if00-port0' 
baud_rate = 115200

# Create a serial object
ser = serial.Serial(serial_port,
                     baudrate=baud_rate,
                     timeout=5.0,
                     bytesize=8,
                     parity='N',
                     stopbits=1)

# MQTT Param for Astar
connect_web = mqtt_publisher.connect()
status = 'A55A21001' # Generate Astar for Local Nav
id_web = 1

def fl_cal(width_pixel, known_distance, known_width):
    return (width_pixel * known_distance)/known_width

def estimate_distance(known_width, width_pixel, focal_length):
    """Estimate the distance from the camera to the object."""
    return abs(known_width * focal_length) / width_pixel

def euclidean_distance(point1, point2):
    return np.sqrt((point1[0] - point2[0]) ** 2 + (point1[1] - point2[1]) ** 2)

while True:
    ret, frame = webcamera.read()
    if not ret:
        break

    font = cv2.FONT_HERSHEY_SIMPLEX
    new_frame_time = time.time()
    fps = 1 / (new_frame_time - prev_frame_time)
    prev_frame_time = new_frame_time
    fps = int(fps)
    fps = str(fps)

    # Perform object detection
    results = model.track(frame, persist=True)
    
    # Calculate the center of the image for direction calculation
    image_center = frame.shape[1] / 2
    
    # Draw FPS on the frame
    cv2.putText(frame, fps, (7, 20), font, 1, (100, 255, 0), 1, cv2.LINE_AA)
    
    # Create centroid list of objects
    centroids = []
    

    for r in results :
        # Get the boxes and track IDs
        boxes = r.boxes

        # Visualize the results on the frame
        annotated_frame = results[0].plot()

        #if there's no item, continue
        if results[0].boxes is None or results[0].boxes.id is None:
            continue
        track_ids = results[0].boxes.id.int().cuda().tolist()

        for box, track_id in zip(boxes, track_ids):
            x1, y1, x2, y2 = box.xyxy[0]
            id = box.id.cuda()
            classes = int(box.cls.cuda())
            w_pix = x2 - x1
            perceived_height = y2 - y1
            object_center = (x1 + x2) / 2

            
            centroid = ((x1 + x2) / 2, (y1 + y2) / 2)
            centroids.append(centroid)
            # focal = fl_cal(w_pix, KNOWN_DIST, KNOWN_WIDTH)
            # print(focal)
            
            
            if classes == 0:
                distance = estimate_distance(KNOWN_WIDTH, w_pix, FOCAL_LENGTH[0])
                # print(distance)
            elif classes == 1:
                distance = estimate_distance(KNOWN_WIDTH, w_pix, FOCAL_LENGTH[1])
                # print(distance)
            
            if object_center < image_center: 
                direction = 'right'
            else: direction = 'left'

            min_dist_0 = 100
            min_dist_1 = 100
            min_gap = 450          # +-50 cm

            if classes == 0 and distance < min_dist_0 and direction == 'right':
                print("---STOP---")
                data_parser.send_command(ser,0,0,0,0) # kanan-kiri, maju-mundur, rotation
                set_block = 'A55A21020N01P02P00P02' # set block-kiri
                mqtt_publisher.publish(connect_web, set_block)
                for i in range(5):
                    print("STOP", i + 1)
                    time.sleep(1)
                
                print("------Kanan")
                data_parser.send_command(ser,id_web,1000,0,0) # kanan-kiri, maju-mundur, rotation
                for i in range(5):
                    print("RUNNING", i + 1)
                    time.sleep(1)

                status = 'A55A21001' # Generate Astar
                mqtt_publisher.publish(connect_web, status)
                id_web += 1

            elif classes == 0 and distance <= min_dist_0 and direction == 'left':
                print("---STOP---")
                data_parser.send_command(ser,0,0,0,0) # kanan-kiri, maju-mundur, rotation
                set_block = 'A55A21020P00P02P01P02' # set block-kanan
                mqtt_publisher.publish(connect_web, set_block)
                for i in range(5):
                    print("STOP", i + 1)
                    time.sleep(1)
                                
                print("------Kiri")
                data_parser.send_command(ser,id_web,-1000,0,0) # kanan-kiri, maju-mundur, rotation
                for i in range(5):
                    print("RUNNING", i + 1)
                    time.sleep(1)

                status = 'A55A21001' # Generate Astar
                mqtt_publisher.publish(connect_web, status)
                id_web += 1

            elif classes == 1 and distance <= min_dist_1:
                print("---STOP---")
                data_parser.send_command(ser,0,0,0,0) # kanan-kiri, maju-mundur, rotation
                for i in range(5):
                    print("STOP", i + 1)
                    time.sleep(1)
                
                status = 'A55A21001'
                mqtt_publisher.publish(connect_web, status)

            # else:
                # print("---CLEAR---")
                # data_parser.send_command(ser,id_web,200,0,0) # kanan-kiri, maju-mundur, rotation
                # id_web += 1

            

            if len(centroids) > 1 and distance < 150:
                gap = np.full((len(centroids), len(centroids)), np.inf)
                for i, point1 in enumerate(centroids):
                    for j, point2 in enumerate(centroids):
                        if i != j:
                            gap[i][j] = euclidean_distance(point1, point2)

                # Find the pair with the shortest distance
                i, j = np.unravel_index(gap.argmin(), gap.shape)
                shortest_gap = gap[i][j]
                print(int(shortest_gap))


                if int(shortest_gap) < min_gap and distance <= 100:
                    print('---BLOCKED---')
                    
                    print("---STOP---")
                    data_parser.send_command(ser,0,0,0,0) # kanan-kiri, maju-mundur, rotation
                    
                    # OBJECT POSITION BASED ON PIXEL FRAME
                    if object_center <= 280:
                        set_pos = 'left'
                    
                    elif 281 <= object_center <= 340:
                        set_pos = 'mid'
                    
                    else: set_pos = 'right'

                    # SET BLOCK BASED ON OBJECT POSITION
                    if set_pos == 'mid' and w_pix <= 352:
                        set_block = 'A55A21020P00P02P00P03'
                        mqtt_publisher.publish(connect_web, set_block)
                    
                    elif set_pos == 'mid' and w_pix > 352:
                        set_block = 'A55A21060N01P02N01P03P00P02P00P03P01P02P01P03'
                        mqtt_publisher.publish(connect_web, set_block)

                    elif set_pos == 'left' and w_pix <= 352:
                        set_block = 'A55A21020N01P02N01P03'
                        mqtt_publisher.publish(connect_web, set_block)
                    
                    elif set_pos == 'left' and w_pix > 352:
                        set_block = 'A55A21040N02P02N02P03N01P02N01P03'
                        mqtt_publisher.publish(connect_web, set_block)
                    
                    elif set_pos == 'right' and w_pix <= 352:
                        set_block = 'A55A21020P01P02P01P03'
                        mqtt_publisher.publish(connect_web, set_block)
                    
                    elif set_pos == 'right' and w_pix > 352:
                        set_block = 'A55A21040P01P02P01P03P02P02P02P03'
                        mqtt_publisher.publish(connect_web, set_block)

                    for i in range(5):
                        print("STOP", i + 1)
                        time.sleep(1)
                
                    status = 'A55A21001'
                    mqtt_publisher.publish(connect_web, status)
                    # status = 'A55A21041P00P03P01P03P02P03P03P03'
                    # mqtt_publisher.publish(connect_web, status)
                
                

    # Loop through detected objects
            cv2.putText(annotated_frame, f'Distance: {int(distance):.2f}cm', (int(x1), int(y1) + 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
            cv2.putText(annotated_frame, f'Direction: {direction}', (int(x1), int(y2) + 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)

        # print(centroids)
    # Display the total count of detected objects
    cv2.putText(annotated_frame, f"Total: {len(results[0].boxes)}", (10, 320), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2, cv2.LINE_AA)

    # Show the annotated_frame with detections
    cv2.imshow("Live Camera", annotated_frame)

    if cv2.waitKey(1) == ord('q'):
        break

webcamera.release()
cv2.destroyAllWindows()