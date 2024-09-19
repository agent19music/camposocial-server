from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import random
from faker import Faker

from models import db, Users, Events, Products, Fun_times, Likes, Comment_events, Comment_fun_times, Reviews
from app import app

fake = Faker()

def seed_data():
    Department_category = ['Software Dev', 'Data Science', 'Cybersec', 'UI/UX']
    # Create users
    user1 = Users(
        first_name='James',
        last_name='Saningo',
        # email to be first_name.last_name@student.com
        email = 'James' + '.' + 'Saningo' + '@student.com',
        phone_no = '0757720955',
        password = fake.password(),
        category=random.choice(Department_category),
        image_url= 'https://media.istockphoto.com/id/1476170969/photo/portrait-of-young-man-ready-for-job-business-concept.webp?b=1&s=612x612&w=0&k=20&c=A87DXDjXjoyJWkWIlLfhJYsjqKtTyuvhOg14QY4SeMQ=',
        gender = 'Male',
        created_at=datetime.now(),
        updated_at=datetime.now(),
        username = fake.user_name()  
        
    )
    user2 = Users(
        first_name='Jane',
        last_name='Ashley',
        email = 'Jane' + '.' + 'Ashley' + '@student.com',
        phone_no = '0757720955',
        password = fake.password(),
        category=random.choice(Department_category),
        image_url = 'https://media.istockphoto.com/id/1430990251/photo/young-woman-on-a-pink-background.webp?b=1&s=612x612&w=0&k=20&c=AM4xGj2PRqSTTUO2pqWI6_qaOCSCXpHv5WmSjvyx7y4=',
        gender = 'Female',
        created_at=datetime.now(),
        updated_at=datetime.now(),
        username = fake.user_name()

    )

    user3 = Users(
        first_name='Caleb',
        last_name='Kamenju',
        email = 'Caleb' + '.' + 'Kamenju' + '@student.com',
        phone_no = '0757720955',
        password = fake.password(),
        category=random.choice(Department_category),
        image_url = 'https://media.istockphoto.com/id/1427894275/photo/portrait-of-bearded-man-in-cap-posing-in-profile-outdoors-profile-view-of-bearded-young-man.webp?b=1&s=612x612&w=0&k=20&c=KOEpjBlQ8OVvD6si6dm5Sx0MI5Ym4RC44DI0HDUSqrk=',
        gender = 'Male',
        created_at=datetime.now(),
        updated_at=datetime.now(),
        username = fake.user_name()
    )

    user4 = Users(
        first_name='Michael',
        last_name='Thomas',
        email = 'Michael' + '.' + 'Thomas' + '@student.com',
        phone_no = '0757720955',
        password = fake.password(),
        category=random.choice(Department_category),
        image_url = 'https://media.istockphoto.com/id/1411453021/photo/skull.webp?b=1&s=612x612&w=0&k=20&c=7Iue-WWFmLmmtDaPKbpOrY-9HpbJaiMQzms7lmTf4Xg=',
        gender = 'Male',
        created_at=datetime.now(),
        updated_at=datetime.now(),
        username = fake.user_name()
    )

    user5 = Users(
        first_name='Victor',
        last_name='Makanda',
        email =  'Victor' + '.' + 'Makanda' + '@student.com',
        phone_no = '0757720955',
        password = fake.password(),
        category=random.choice(Department_category),
        image_url = 'https://media.istockphoto.com/id/1636022764/photo/basketball-ball.webp?b=1&s=612x612&w=0&k=20&c=0y57uYhHgKRzKni01eW-mrPFUX0EwF_vuOtdFgKJ8HM=',
        gender = 'Male',
        created_at=datetime.now(),
        updated_at=datetime.now(),
        username = fake.user_name()
    )

    db.session.add_all([user1, user2, user3, user4, user5])
    db.session.commit()

    # Create categories
    product_categories = ['Food', 'Tech', 'Accessories', 'Clothing', 'Art']
    

    # Create products
    Product1 = Products(
        title = 'hat',
        description = 'Christmas hat, brand new and in great condition',
        image_url = 'https://media.istockphoto.com/id/183296619/photo/a-festive-red-and-white-santa-hat-on-a-white-background.webp?b=1&s=612x612&w=0&k=20&c=rK8f2eEan5m2EgcaaG-Pspkf6r0AxQ_rhpbf-RRFWM8=',
        price = 500,
        category = 'Clothing',
        contact_info = '0757720955',
        created_at=datetime.now(),
        updated_at=datetime.now(),
        user_id = user1.id
    )

    Product2 = Products(
        title = 'laptop',
        description = 'Macbook Pro, 1TB storge, M3 Max Chip, Retina Display and 17 inch screen display',
        image_url = 'https://media.istockphoto.com/id/1394988455/photo/laptop-with-a-blank-screen-on-a-white-background.webp?b=1&s=612x612&w=0&k=20&c=VCCVeK25QpSCdGjiDgeviwz2pJfikLyclwhX-MQblhg=',
        price = 70000,
        category = 'Tech',
        contact_info = '0757720955',
        created_at=datetime.now(),
        updated_at=datetime.now(),
        user_id = user2.id
    )

    Product3 = Products(
        title = 'shoes',
        description = 'Sneakers, black and white, size 9',
        image_url = 'https://media.istockphoto.com/id/1417090656/photo/white-leather-sneaker.webp?b=1&s=612x612&w=0&k=20&c=5OnRo8238WuK1-rE0__0QTj182DDDDFNXF_JhKpOOW8=',
        price = 3000,
        category = 'Clothing',
        contact_info = '0757720955',
        created_at=datetime.now(),
        updated_at=datetime.now(),
        user_id = user3.id
    )

    Product4 = Products(
        title = 'Sandwitch',
        description = 'Sandwitch with ham, cheese, lettuce, onion, mortadella, and sausage',
        image_url = 'https://media.istockphoto.com/id/1410104632/photo/submarine-sandwich-with-ham-cheese-lettuce-tomatoes-onion-mortadella-and-sausage.webp?b=1&s=612x612&w=0&k=20&c=ZSctN5ADLMdw5aWSNGz6xOC0hqdAZmZGfq6JlxiR6EA=',
        price = 250,
        category = 'Food',
        contact_info = '0757720955',
        created_at=datetime.now(),
        updated_at=datetime.now(),
        user_id = user4.id
    )
    
    Product5 =  Products(
        title = 'Painting',
        description = 'A modern painting on canvas',
        image_url = 'https://media.istockphoto.com/id/1416014146/photo/abstract-modern-painting-background.webp?b=1&s=612x612&w=0&k=20&c=FydWvdPGmfexXB_Y1b_LHFvAWTkHLINizwqqYfchl_U=',
        price = 2500,
        category = 'Art',
        contact_info = '0757720955',
        created_at=datetime.now(),
        updated_at=datetime.now(),
        user_id = user5.id
    )

    Product6 =  Products(
        title = 'necklace',
        description = 'Silver necklace for casual wear',
        image_url = 'https://media.istockphoto.com/id/1389474559/photo/solitaire-diamond-necklace.webp?b=1&s=612x612&w=0&k=20&c=Pkvz5ZUiJYRNHKT-bj2LQQNIuQXfQE_4oJD-t3BYzWQ=',
        price = 1000,
        category = 'Accessories',
        contact_info = '0757720955',
        created_at=datetime.now(),
        updated_at=datetime.now(),
        user_id = user2.id
    )
    
    Product7 =  Products(
        title = 'Cool Tech Gadgets',
        description = 'Coolest gadgets like computers, laptops, and USB devices are essential tools for modern living, offering unparalleled !!',
        image_url = 'https://feeds.abplive.com/onecms/images/uploaded-images/2022/10/30/9cabeacaf13ae35cef67a86a6f8b2fb51667143402677460_original.jpg',
        price = 5000,
        category = 'Tech',
        contact_info = '0757720955',
        created_at=datetime.now(),
        updated_at=datetime.now(),
        user_id = user3.id
    )

    Product8 =  Products(
        title = 'Laptop and Phone Covers',
        description = 'Purchasing a laptop cover ensures protection against scratches, spills, and impact damage, prolonging the lifespan of for',
        image_url = 'https://intergratedcomputers.co.ke/wp-content/uploads/2018/05/Laptop-covers-4in1-3.jpg',
        price = 1000,
        category = 'Accessories',
        contact_info = '0757720955',
        created_at=datetime.now(),
        updated_at=datetime.now(),
        user_id = user4.id
    )

    Product9 =  Products(
        title = 'Urban Street-wear',
        description = 'Acquiring our latest urban wear shirts allows individuals to stay on-trend and express their unique style within contemporary',
        image_url = 'https://i.etsystatic.com/11384846/r/il/9c867b/2339923257/il_1140xN.2339923257_m1x7.jpg',
        price = 1500,
        category = 'Clothing',
        contact_info = '0757720955',
        created_at=datetime.now(),
        updated_at=datetime.now(),
        user_id = user1.id
    )

    db.session.add_all([Product1, Product2, Product3, Product4, Product5, Product6, Product7, Product8, Product9])
    db.session.commit()

    # Create reviews for products
    Review1 = Reviews(
        text = 'Really liked the hat',
        user_id = user2.id,
        rating = 4.5,
        product_id = Product1.id
    )

    Review2 = Reviews(
        text = 'Got the PS5 from here no regrets fr',
        user_id = user1.id,
        rating = 4.5,
        product_id = Product7.id
    )

    Review3 = Reviews(
        text = 'High quality gadgets',
        user_id = user3.id,
        rating = 4.0,
        product_id = Product8.id
    )

    Review4 = Reviews(
        text = 'yoh great service',
        user_id = user4.id,
        rating = 4.2,
        product_id = Product9.id
    )

    Review5 = Reviews(
        text = 'yoh great service',
        user_id = user4.id,
        rating =4.2,
        product_id = Product7.id
    )

    Review6 = Reviews(
        text = 'yoh great service',
        user_id = user4.id,
        rating =4.2,
        product_id = Product8.id
    )

    db.session.add_all([Review1, Review2, Review3, Review4, Review5, Review6])
    db.session.commit()

    event_categories = ['Funny', 'Education', 'Social']
    # Create events
    Event1 = Events(
        title = 'Melissa Birthday',
        description = 'Join us for a fun-filled birthday bash!',
        image_url = 'https://i.pinimg.com/736x/3f/dd/f3/3fddf393f6630954ee6e89a740348be6.jpg',
        start_time = datetime.now(),
        end_time = datetime.now(),
        date_of_event = datetime.now(),
        Entry_fee = 'Free',
        category = 'Social',
        created_at=datetime.now(),
        updated_at=datetime.now(),
        user_id = user2.id
    )

    Event2 = Events(
        title = 'Exams',
        description = 'Physics exam at 3pm on Friday',
        image_url = 'https://media.istockphoto.com/id/525409577/photo/elevated-view-of-students-writing-their-gcse-exam.webp?b=1&s=612x612&w=0&k=20&c=vmUZFZlKxFWmec_Nn3B4wFkHxByTKOZfvfM8qx1IriQ=',
        start_time = datetime.now(),
        end_time = datetime.now(),
        date_of_event = datetime.now(),
        Entry_fee = '500',
        category = 'Education',
        created_at=datetime.now(),
        updated_at=datetime.now(),
        user_id = user1.id
    )

    Event3 = Events(
        title = 'Crazy After Party',
        description = 'Millidos after party',
        image_url = 'https://i.pinimg.com/564x/65/e5/9c/65e59c59a2f0f841a7785386b88f5329.jpg',
        start_time = datetime.now(),
        end_time = datetime.now(),
        date_of_event = datetime.now(),
        Entry_fee = '1000',
        category = 'Fun',
        created_at=datetime.now(),
        updated_at=datetime.now(),
        user_id = user1.id

    )

    Event4 =  Events(
        title = 'Kendrick 2022',
        description = 'I remember you was conflicted. Misguided by your influence',
        image_url = 'https://store.friendlyarcticprinting.com/cdn/shop/products/Kendrick_Lamar_ORANGE-poster_1_copy_2400x.jpg?v=1553625706',
        start_time = datetime.now(),
        end_time = datetime.now(),
        date_of_event = datetime.now(),
        Entry_fee = 'Free',
        category = 'Fun',
        created_at=datetime.now(),
        updated_at=datetime.now(),
        user_id = user1.id

    )

    Event5 =  Events(
        title = 'Look Mom I Can Fly',
        description = 'Come experience the travis scott experience with us',
        image_url = 'https://pbs.twimg.com/media/EV1ph6_XYAAn_92.jpg',
        start_time = datetime.now(),
        end_time = datetime.now(),
        date_of_event = datetime.now(),
        Entry_fee = 'Free',
        category = 'Social',
        created_at=datetime.now(),
        updated_at=datetime.now(),
        user_id = user1.id

    )

    Event7 =  Events(
        title = 'Call Me If You Get Lost',
        description = 'Is that potato salad ? Come see TYler live at the RU Gardens Thursday 12/07/24 from 2pm to 8pm',
        image_url = 'https://media.contra.com/image/upload/gggrcvnwy9pebj4lrhkk',
        start_time = datetime.now(),
        end_time = datetime.now(),
        date_of_event = datetime.now(),
        Entry_fee = '$2,000',
        category = 'Social',
        created_at=datetime.now(),
        updated_at=datetime.now(),
        user_id = user1.id

    )

    
    db.session.add_all([Event1, Event2, Event3, Event4, Event5, Event7])
    db.session.commit()

    # Create comments for events
    EComment1 = Comment_events(
        text = 'Cheers to another year to live',
        user_id = user1.id,
        event_id = Event1.id,
        created_at=datetime.now(),
        updated_at=datetime.now()

       )

    EComment2 = Comment_events(
        text = 'Na si hiyo exam imetuwahi',
        user_id = user2.id,
        event_id = Event2.id,
        created_at=datetime.now(),
        updated_at=datetime.now()
       )

    EComment3 = Comment_events(
        text = 'Great Party Saningo',
        user_id = user3.id,
        event_id = Event3.id,
        created_at=datetime.now(),
        updated_at=datetime.now()
       )

    Ecomment4 =  Comment_events(
        text = 'Kendrick Lamar the goat I swear bro lets goo',
        user_id = user4.id,
        event_id = Event4.id,
        created_at=datetime.now(),
        updated_at=datetime.now()
       )

    Ecomment5 =  Comment_events(
        text = 'Go ballistic',
        user_id = user4.id,
        event_id = Event5.id,
        created_at=datetime.now(),
        updated_at=datetime.now()
       )
    

    Ecomment6 =  Comment_events(
        text = 'Awesome movie',
        user_id = user2.id,
        event_id = Event7.id,
        created_at=datetime.now(),
        updated_at=datetime.now()
       )

    db.session.add_all([EComment1, EComment2, EComment3, Ecomment4, Ecomment5, Ecomment6])
    db.session.commit()

    fun_time_categories = ['Funny', 'Educational', 'Events']
    # Create fun times
    FunTime1 =  Fun_times(
        description = 'City under the sun',
        image_url = 'https://i.pinimg.com/564x/89/75/a3/8975a3b82eb75b073b222d549c99fdfb.jpg',
        category = 'Events',
        created_at=datetime.now(),
        updated_at=datetime.now(),
        user_id = user4.id
    )

    FunTime2 =  Fun_times(
        description = '7pm in RU',
        image_url = 'https://i.pinimg.com/564x/d8/d5/b5/d8d5b597dca05b0b52cd31feff0597e5.jpg',
        category = 'Funny',
        created_at=datetime.now(),
        updated_at=datetime.now(),
        user_id = user1.id
    )

    FunTime3 =  Fun_times(
        description = 'Miss. Fox was fired today',
        image_url = 'https://i.pinimg.com/736x/17/fa/44/17fa44e8d7f0d4a341f078b6c94a31ef.jpg',
        category = 'Educational',
        created_at=datetime.now(),
        updated_at=datetime.now(),
        user_id = user5.id
    )

    FunTime4 =  Fun_times(
        description = 'Finally got to SEE TRAVIS LIIVEEE',
        image_url = 'https://i.pinimg.com/564x/2e/68/23/2e682332419f7145771eaa26125b010b.jpg',
        category = 'Event',
        created_at=datetime.now(),
        updated_at=datetime.now(),
        user_id = user2.id
    )

    FunTime5 =  Fun_times(
        description = 'Big Steppers Tour Lets gooo',
        image_url = 'https://i.pinimg.com/564x/3e/78/d3/3e78d3582297bc16554045e0fbc9497c.jpg',
        category = 'Event',
        created_at=datetime.now(),
        updated_at=datetime.now(),
        user_id = user3.id
    )

    FunTime6 =  Fun_times(
        description = 'TYLERRRR OMFGGGGG',
        image_url = 'https://i.pinimg.com/564x/17/ab/1b/17ab1b71bc31f840dad7a948adb6fcf3.jpg',
        category = 'Event',
        created_at=datetime.now(),
        updated_at=datetime.now(),
        user_id = user4.id
    )

    FunTime7 =  Fun_times(
        description = 'Calm Luh Fit',
        image_url = 'https://i.pinimg.com/736x/87/31/db/8731db5f8fe89fb9bde6936710471345.jpg',
        category = 'Funny',
        created_at=datetime.now(),
        updated_at=datetime.now(),
        user_id = user1.id
    )




    db.session.add_all([FunTime1, FunTime2, FunTime3, FunTime4, FunTime5, FunTime6, FunTime7])
    db.session.commit()
    

    # Create likes for fun times
    Like1= Likes(
        user_id = user1.id,
        fun_time_id = FunTime1.id
    )

    Like2= Likes(
        user_id = user2.id,
        fun_time_id = FunTime2.id
    )

    Like3= Likes(
        user_id = user3.id,
        fun_time_id = FunTime3.id
    )

    Like4= Likes(
        user_id = user3.id,
        fun_time_id = FunTime4.id
    )

    Like5= Likes(
        user_id = user4.id,
        fun_time_id = FunTime5.id
    )

    Like6= Likes(
        user_id = user5.id,
        fun_time_id = FunTime6.id
    )

    Like7= Likes(
        user_id = user1.id,
        fun_time_id = FunTime7.id
    )

    db.session.add_all([Like1, Like2, Like3, Like4, Like5, Like6, Like7])
    db.session.commit()

    

    # Create comments for fun times
    FComment1 = Comment_fun_times(
        text = 'Crazy clear picture',
        user_id = user1.id,
        fun_time_id = FunTime1.id,
        created_at=datetime.now(),
        updated_at=datetime.now()

        )

    FComment2 = Comment_fun_times(
        text = 'LMAO',
        user_id = user2.id,
        fun_time_id = FunTime2.id,
        created_at=datetime.now(),
        updated_at=datetime.now()
        )

    FComment3 = Comment_fun_times(
        text = 'Ohh no she was my English teacher',
        user_id = user3.id,
        fun_time_id = FunTime3.id,
        created_at=datetime.now(),
        updated_at=datetime.now()
        )

    FComment4 = Comment_fun_times(
        text = 'Loved the concert',
        user_id = user4.id,
        fun_time_id = FunTime4.id,
        created_at=datetime.now(),
        updated_at=datetime.now()
        )

    FComment5 = Comment_fun_times(
        text = 'Am so jealous',
        user_id = user5.id,
        fun_time_id = FunTime5.id,
        created_at=datetime.now(),
        updated_at=datetime.now()
        )

    FComment6 = Comment_fun_times(
        text = 'OMG ITS TYLER',
        user_id = user1.id,
        fun_time_id = FunTime6.id,
        created_at=datetime.now(),
        updated_at=datetime.now()
        )

    FComment7 = Comment_fun_times(
        text = 'Love the fit bro',
        user_id = user3.id,
        fun_time_id = FunTime7.id,
        created_at=datetime.now(),
        updated_at=datetime.now()
        )

    db.session.add_all([FComment1, FComment2, FComment3, FComment4, FComment5, FComment6, FComment7])
    db.session.commit()

    
if __name__ == '__main__':
   with app.app_context():
        db.drop_all()
        db.create_all()
        seed_data()
        print("Data seeded successfully!")



# from flask import Flask
# from flask_sqlalchemy import SQLAlchemy
# from datetime import datetime
# import random
# from faker import Faker

# from models import db, Users, Events, Products, Fun_times, Likes, Comment_events, Comment_fun_times, Reviews
# from app import app

# fake = Faker()

# def seed_data():
#     # Create users
#     for _ in range(50):
#         user = Users(
#             first_name=fake.first_name(),
#             last_name=fake.last_name(),
#             email=fake.email(),
#             phone_no='0757720955',
#             password=fake.password(),
#             category=random.choice(['Software Dev', 'Data Science', 'Cybersec', 'UI/UX']),
#             image_url='https://example.com/john.jpg',
#             gender=random.choice(['male', 'female']),
#             created_at=datetime.now(),
#             updated_at=datetime.now(),
#             username=fake.user_name()
#         )
#         db.session.add(user)
#     db.session.commit()

#     # Create categories
#     product_categories = ['Food', 'Tech', 'Accessories', 'Clothing', 'Art']
#     fun_time_categories = ['Funny', 'Educational', 'Events']

#     # Create products
#     for _ in range(50):
#         product = Products(
#             title=fake.word(),
#             description=fake.sentence(),
#             image_url=fake.image_url(),
#             price=random.randint(10, 1000),
#             category=random.choice(product_categories),
#             created_at=datetime.now(),
#             updated_at=datetime.now(),
#             user_id=random.randint(1, 50)
#         )
#         db.session.add(product)
#     db.session.commit()

#     # Create reviews for products
#     for product in Products.query.all():
#         for _ in range(random.randint(1, 5)):
#             review = Reviews(
#                 text=fake.paragraph(),
#                 user_id=random.randint(1, 50),
#                 rating=random.randint(1, 5),
#                 product_id=product.id
#             )
#             db.session.add(review)
#     db.session.commit()

#     # Create events
#     for _ in range(20):
#         event = Events(
#             title=fake.sentence(),
#             description=fake.paragraph(),
#             image_url=fake.image_url(),
#             start_time=fake.date_time_this_month(),
#             end_time=fake.date_time_this_month(),
#             date_of_event=fake.date_this_month(),
#             category = random.choice(['Fun', 'Education', 'Social']),
#             created_at=datetime.now(),
#             updated_at=datetime.now(),
#             user_id=random.randint(1, 50)
#         )
#         db.session.add(event)
#     db.session.commit()
    
#     # Create fun times
#     for _ in range(30):
#         fun_time = Fun_times(
#             description=fake.paragraph(),
#             image_url=fake.image_url(),
#             category=random.choice(fun_time_categories),
#             created_at=datetime.now(),
#             updated_at=datetime.now(),
#             user_id=random.randint(1, 50)
#         )
#         db.session.add(fun_time)
#     db.session.commit()

#     # Create likes for fun times
#     for _ in range(50):
#         like = Likes(
#             user_id=random.randint(1, 50),
#             fun_time_id=random.randint(1, 30)
#         )
#         db.session.add(like)
#     db.session.commit()

#     # Create comments for events
#     for event in Events.query.all():
#         for _ in range(random.randint(1, 5)):
#             comment_event = Comment_events(
#                 text=fake.paragraph(),
#                 user_id=random.randint(1, 50),
#                 event_id=event.id,
#                 created_at=datetime.now(),
#                 updated_at=datetime.now()
#             )
#             db.session.add(comment_event)
#     db.session.commit()

#     # Create comments for fun times
#     for fun_time in Fun_times.query.all():
#         for _ in range(random.randint(1, 5)):
#             comment_fun_time = Comment_fun_times(
#                 text=fake.paragraph(),
#                 user_id=random.randint(1, 50),
#                 fun_time_id=fun_time.id , # Corrected attribute name,
#                 created_at=datetime.now(),
#                 updated_at=datetime.now()
#             )
#             db.session.add(comment_fun_time)
#     db.session.commit()

    
# if __name__ == '__main__':
#    with app.app_context():
#         db.drop_all()
#         db.create_all()
#         seed_data()
#         print("Data seeded successfully!")

